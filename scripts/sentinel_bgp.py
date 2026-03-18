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
from datetime import datetime, timezone

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
GOBGP_CONFIG_PATH = "/etc/gobgp/gobgpd.conf"


def get_db():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    return client[MONGO_DB]


def get_local_ip() -> str:
    """Auto-detect primary IP of this machine."""
    if LOCAL_ROUTER_ID:
        return LOCAL_ROUTER_ID
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
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
                "as": LOCAL_AS,
                "router-id": router_id,
                "listen-port": 179,
            }
        },
        "neighbors": []
    }

    for peer in peers:
        neighbor_ip = peer.get("ip_address", "").split(":")[0].strip()
        if not neighbor_ip:
            continue
        peer_as = peer.get("bgp_peer_as", LOCAL_AS)  # Default iBGP
        config["neighbors"].append({
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
            "afi-safis": [
                {
                    "config": {
                        "afi-safi-name": "ipv4-unicast",
                    }
                }
            ]
        })

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
            conf = n.get("conf", {}).get("neighbor-address", "unknown")
            state = n.get("state", {})
            session_state = state.get("session-state", "unknown")
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

    # Add peers via gobgp CLI (runtime, no restart needed)
    for device in devices:
        ip = device.get("ip_address", "").split(":")[0].strip()
        if not ip:
            continue
        peer_as = device.get("bgp_peer_as", LOCAL_AS)
        ok, out = run_cmd([
            GOBGP_BIN, "neighbor", "add", ip,
            "as", str(peer_as),
            "--address-family", "ipv4"
        ])
        if ok:
            logger.info(f"BGP peer {ip} (AS{peer_as}) added/updated")
        else:
            if "already exists" in out.lower():
                pass  # Normal
            else:
                logger.warning(f"Failed to add BGP peer {ip}: {out}")


def persist_bgp_status(db, status: list[dict]):
    """Save BGP status snapshot to MongoDB for the frontend to read."""
    now = datetime.now(timezone.utc).isoformat()
    db.peering_eye_bgp_status.delete_many({})  # Keep only latest
    if status:
        docs = [{**s, "updated_at": now} for s in status]
        db.peering_eye_bgp_status.insert_many(docs)
        logger.info(f"BGP status persisted: {len(docs)} peers")


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
                "as": LOCAL_AS,
                "router-id": router_id,
                "listen-port": 179,
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
        subprocess.Popen(
            [GOBGPD_BIN, "-f", GOBGP_CONFIG_PATH, "--log-level", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(2)
        logger.info("gobgpd starte attempt finished")
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
