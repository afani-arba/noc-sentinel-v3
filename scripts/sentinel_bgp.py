#!/usr/bin/env python3
"""
Sentinel Peering-Eye — BGP Speaker Connector
=============================================
Menggunakan GoBGP (yang diinstall di Ubuntu) via REST API lokal.

Fungsi:
  - Membaca konfigurasi peer dari MongoDB (devices collection)
  - Memastikan sesi iBGP terjaga ke semua Mikrotik yang dikonfigurasi
  - Expose status peer ke API backend
  - Optional: push prefix per-platform ke Mikrotik sebagai Address-List via BGP community

Requirements (Ubuntu):
  - GoBGP terinstall: https://github.com/osrg/gobgp
  - gobgpd berjalan dengan konfigurasi yang sesuai

Env vars:
  MONGO_URL          : MongoDB URL (default: mongodb://localhost:27017)
  MONGO_DB           : DB name (default: noc_sentinel)
  GOBGP_API          : GoBGP gRPC API address (default: localhost:50051)
  LOCAL_AS           : AS Number lokal Ubuntu (default: 65000)
  LOCAL_ROUTER_ID    : Router-ID Ubuntu (default: auto-detect)
"""

import os
import time
import json
import logging
import socket
import subprocess
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sentinel-bgp")

# ── Config ─────────────────────────────────────────────────────────────────────
MONGO_URL      = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB       = os.getenv("MONGO_DB", "noc_sentinel")
GOBGP_BIN      = os.getenv("GOBGP_BIN", "/usr/local/bin/gobgp")
GOBGPD_BIN     = os.getenv("GOBGPD_BIN", "/usr/local/bin/gobgpd")
LOCAL_AS       = int(os.getenv("LOCAL_AS", "65000"))
LOCAL_ROUTER_ID = os.getenv("LOCAL_ROUTER_ID", "")
SYNC_INTERVAL  = int(os.getenv("BGP_SYNC_INTERVAL", "300"))  # 5 menit
GOBGP_CONFIG_PATH = "/etc/gobgp/gobgpd.json"

PLATFORM_COMMUNITIES = {
    "YouTube": "65000:10",
    "Netflix": "65000:11",
    "TikTok": "65000:12",
    "Facebook": "65000:13",
    "Instagram": "65000:14",
    "WhatsApp": "65000:15",
    "Telegram": "65000:16",
    "LINE": "65000:17",
    "Discord": "65000:18",
    "Zoom": "65000:19",
    "Shopee": "65000:20",
    "Tokopedia": "65000:21",
    "Gojek/GoTo": "65000:22",
    "Grab": "65000:23",
    "Mobile Legends": "65000:30",
    "PUBG Mobile": "65000:31",
    "Roblox": "65000:32",
    "Steam": "65000:33",
    "Google": "65000:100",
}


def get_db():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    return client[MONGO_DB]


def get_local_ip() -> str:
    """Auto-detect primary IP of this machine with retries."""
    if LOCAL_ROUTER_ID:
        return LOCAL_ROUTER_ID
    
    for _ in range(10):  # Retry up to 10 times (Useful during system boot)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            time.sleep(2)
            
    return "127.0.0.1"


def run_cmd(cmd: list[str]) -> tuple[bool, str]:
    """Run a shell command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, str(e)


def generate_gobgp_config(peers: list[dict]) -> str:
    """Generate GoBGP TOML configuration from peer list."""
    router_id = get_local_ip()

    config = {
        "global": {
            "config": {
                "as": int(LOCAL_AS),
                "router-id": router_id
            },
            "apply-policy": {
                "config": {
                    "default-import-policy": "accept-route",
                    "default-export-policy": "accept-route"
                }
            }
        },
        "neighbors": []
    }

    seen_ips = set()
    for peer in peers:
        neighbor_ip = peer.get("ip_address", "").split(":")[0].strip()
        if not neighbor_ip or neighbor_ip in seen_ips:
            continue
        seen_ips.add(neighbor_ip)
        peer_as_raw = peer.get("bgp_peer_as", LOCAL_AS)
        try:
            peer_as = int(str(peer_as_raw).strip())
        except ValueError:
            peer_as = int(LOCAL_AS)
            
        neighbor_conf = {
            "config": {
                "neighbor-address": neighbor_ip,
                "peer-as": peer_as,
                "description": peer.get("name", neighbor_ip),
            },
            "timers": {
                "config": {
                    "hold-time": 90,
                    "keepalive-interval": 30,
                }
            },
            "apply-policy": {
                "config": {
                    "default-import-policy": "accept-route",
                    "default-export-policy": "accept-route"
                }
            },
            "afi-safis": [
                {
                    "config": {
                        "afi-safi-name": "ipv4-unicast",
                    }
                }
            ]
        }
        
        if peer_as != int(LOCAL_AS):
            neighbor_conf["ebgp-multihop"] = {
                "config": {
                    "enabled": True,
                    "multihop-ttl": 255
                }
            }
            
        config["neighbors"].append(neighbor_conf)

    # Serialize to JSON (GoBGP also accepts JSON config)
    return json.dumps(config, indent=2)


def get_bgp_neighbors_status() -> list[dict]:
    """Get current BGP neighbor status via gobgp CLI."""
    ok, output = run_cmd([GOBGP_BIN, "neighbor", "-j"])
    if not ok:
        logger.warning(f"gobgp neighbor query failed: {output}")
        return []

    try:
        neighbors = json.loads(output)
        result = []
        for n in neighbors:
            state = n.get("state", {})
            conf = n.get("conf", {}).get("neighbor-address")
            if not conf:
                conf = state.get("neighbor-address", "unknown")
            
            session_state = str(state.get("session-state", "unknown")).upper()
            peer_as = state.get("peer-as", 0)
            pfx = n.get("afi-safis", [{}])[0].get("state", {})
            received  = pfx.get("received", 0)
            accepted  = pfx.get("accepted", 0)
            advertised = pfx.get("advertised", 0)
            uptime_s = state.get("uptime", 0)

            result.append({
                "neighbor_ip":  conf,
                "peer_as":       peer_as,
                "state":         session_state,
                "uptime_sec":    uptime_s,
                "prefixes_rx":   received,
                "prefixes_accepted": accepted,
                "prefixes_tx":   advertised,
            })
        return result
    except json.JSONDecodeError:
        logger.warning("Failed to parse gobgp JSON output")
        return []


def sync_peers_to_gobgp(db):
    """Read BGP-enabled devices from DB and ensure GoBGP has correct config."""
    devices = list(db.devices.find(
        {"bgp_enabled": True},
        {"_id": 0, "id": 1, "name": 1, "ip_address": 1, "bgp_peer_as": 1}
    ))

    if not devices:
        logger.info("No BGP-enabled devices found in DB")
        return

    logger.info(f"Syncing {len(devices)} BGP peers to GoBGP")
    config_json = generate_gobgp_config(devices)

    # Write config to file
    try:
        os.makedirs("/etc/gobgp", exist_ok=True)
        with open(GOBGP_CONFIG_PATH, "w") as f:
            f.write(config_json)
        logger.info(f"GoBGP config written to {GOBGP_CONFIG_PATH}")
    except PermissionError:
        logger.warning("Cannot write /etc/gobgp/gobgpd.conf (need root). Using API instead.")

    # Reload GoBGP config (runtime, no restart needed)
    ok, pid = run_cmd(["pgrep", "-x", "gobgpd"])
    if ok and pid:
        run_cmd(["kill", "-HUP", pid])
        logger.info(f"Sent SIGHUP to gobgpd (PID {pid}) to reload {len(devices)} peers config")
    else:
        logger.warning("Could not find gobgpd process to reload config")


def persist_bgp_status(db, status: list[dict]):
    """Save BGP status snapshot to MongoDB for the frontend to read."""
    now = datetime.now(timezone.utc).isoformat()
    db.peering_eye_bgp_status.delete_many({})  # Keep only latest
    if status:
        docs = [{**s, "updated_at": now} for s in status]
        db.peering_eye_bgp_status.insert_many(docs)
        logger.info(f"BGP status persisted: {len(docs)} peers")


CURRENT_INJECTED = defaultdict(set)

def get_platform_domains(db) -> dict[str, set[str]]:
    domains_by_platform = defaultdict(set)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    
    stats = db.peering_eye_stats.find({"timestamp": {"$gt": cutoff.isoformat()}})
    for stat in stats:
        platform = stat.get("platform")
        if platform in PLATFORM_COMMUNITIES:
            # top_domains is a dict: {"youtube.com": 50, "googlevideo.com": 100}
            top_domains = stat.get("top_domains", {})
            if isinstance(top_domains, dict):
                for domain in top_domains.keys():
                    if domain:
                        domains_by_platform[platform].add(domain)
    return dict(domains_by_platform)


def resolve_domain(domain: str) -> list[str]:
    try:
        _, _, ips = socket.gethostbyname_ex(domain)
        return ips
    except Exception:
        return []


def resolve_all_domains(domains: set[str]) -> set[str]:
    ips = set()
    with ThreadPoolExecutor(max_workers=20) as executor:
        for result in executor.map(resolve_domain, list(domains)):
            ips.update(result)
    return ips


from pymongo import MongoClient, UpdateOne

def sync_platform_ips_to_bgp(db, platform: str, new_ips: set[str]):
    community = PLATFORM_COMMUNITIES.get(platform)
    if not community:
        return

    old_ips = CURRENT_INJECTED.get(platform, set())
    
    bgp_nexthop = os.getenv("BGP_NEXTHOP")
    if not bgp_nexthop:
        bgp_nexthop = get_local_ip()
        
    added = 0
    for ip in new_ips - old_ips:
        ok, _ = run_cmd([GOBGP_BIN, "global", "rib", "add", f"{ip}/32", "nexthop", bgp_nexthop, "community", community])
        if ok: added += 1
            
    deleted = 0
    for ip in old_ips - new_ips:
        ok, _ = run_cmd([GOBGP_BIN, "global", "rib", "del", f"{ip}/32"])
        if ok: deleted += 1
            
    CURRENT_INJECTED[platform] = set(new_ips)
    if added > 0 or deleted > 0:
        logger.info(f"Platform {platform}: Injected {added} new IPs, removed {deleted} stale IPs")
        
        # Save to MongoDB for sentinel_eye.py NetFlow classifier
        try:
            ops = [UpdateOne({"ip": ip}, {"$set": {"platform": platform}}, upsert=True) for ip in new_ips]
            if ops:
                db.peering_eye_ips.bulk_write(ops)
            db.peering_eye_ips.delete_many({"platform": platform, "ip": {"$nin": list(new_ips)}})
        except Exception as e:
            logger.error(f"Failed to persist IPs to MongoDB: {e}")


def bgp_monitor_loop():
    """Main BGP monitoring loop."""
    db = get_db()
    logger.info(f"BGP monitor loop started (sync every {SYNC_INTERVAL}s)")

    while True:
        try:
            # 1. Sync peers from DB to GoBGP
            sync_peers_to_gobgp(db)

            # 2. Get current neighbor status
            status = get_bgp_neighbors_status()

            # 3. Enrich with device names from DB
            devices = {
                d.get("ip_address", "").split(":")[0]: d.get("name", "")
                for d in db.devices.find({}, {"_id": 0, "ip_address": 1, "name": 1})
            }
            for s in status:
                s["device_name"] = devices.get(s["neighbor_ip"], s["neighbor_ip"])

            # 4. Persist to MongoDB
            persist_bgp_status(db, status)

            established = sum(1 for s in status if s["state"] == "ESTABLISHED")
            logger.info(f"BGP sync done: {len(status)} peers, {established} established")

            # 5. Inject prefixes into global RIB (peers will automatically receive them when they connect)
            domains_map = get_platform_domains(db)
            for platform, domains in domains_map.items():
                if not domains: continue
                ips = resolve_all_domains(domains)
                if ips:
                    sync_platform_ips_to_bgp(db, platform, ips)

        except Exception as e:
            logger.error(f"BGP monitor loop error: {e}")

        time.sleep(SYNC_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════════
# GOBGP DAEMON MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

def ensure_gobgpd_running():
    """Check if gobgpd is running; start it if not."""
    ok, out = run_cmd(["pgrep", "-x", "gobgpd"])
    if ok:
        logger.info("gobgpd is already running")
        return True

    logger.info("gobgpd not running, attempting to start...")
    router_id = get_local_ip()

    # Generate minimal config
    minimal_config = json.dumps({
        "global": {
            "config": {
                "as": int(LOCAL_AS),
                "router-id": router_id
            },
            "apply-policy": {
                "config": {
                    "default-import-policy": "accept-route",
                    "default-export-policy": "accept-route"
                }
            }
        }
    })

    os.makedirs("/etc/gobgp", exist_ok=True)
    try:
        with open(GOBGP_CONFIG_PATH, "w") as f:
            f.write(minimal_config)
    except PermissionError:
        logger.error("Need root to write GoBGP config. Run as root or use sudo.")
        return False

    try:
        log_f = open("/var/log/gobgpd.log", "a")
        subprocess.Popen(
            [GOBGPD_BIN, "-f", GOBGP_CONFIG_PATH, "--log-level", "info"],
            stdout=log_f,
            stderr=log_f,
            start_new_session=True
        )
        time.sleep(2)
        logger.info("gobgpd start attempt finished")
        return True
    except Exception as e:
        logger.error(f"Failed to start gobgpd: {e}")
        return False


def main():
    logger.info("=" * 60)
    logger.info("  Sentinel Peering-Eye BGP Speaker v1.0")
    logger.info(f"  Local AS      : {LOCAL_AS}")
    logger.info(f"  Router ID     : {get_local_ip()}")
    logger.info(f"  MongoDB       : {MONGO_URL}/{MONGO_DB}")
    logger.info(f"  Sync interval : {SYNC_INTERVAL}s")
    logger.info("=" * 60)

    # Verify MongoDB
    try:
        db = get_db()
        db.command("ping")
        logger.info("MongoDB connection OK")
        # Ensure indexes
        db.peering_eye_bgp_status.create_index([("neighbor_ip", 1)])
    except Exception as e:
        logger.error(f"MongoDB connection FAILED: {e}")
        raise SystemExit(1)

    # Check for GoBGP binary
    ok, _ = run_cmd(["which", GOBGP_BIN.split("/")[-1]])
    if not ok:
        logger.error(f"gobgp binary not found at {GOBGP_BIN}")
        logger.error("Install GoBGP: https://github.com/osrg/gobgp/releases")
        logger.warning("Running in STATUS-ONLY mode (no BGP peering)")
    else:
        ensure_gobgpd_running()

    # Start BGP monitor loop
    t = threading.Thread(target=bgp_monitor_loop, name="bgp-monitor", daemon=True)
    t.start()
    logger.info("Sentinel BGP Speaker running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Shutting down Sentinel BGP Speaker...")


if __name__ == "__main__":
    main()
