#!/usr/bin/env python3
"""
Sentinel Peering-Eye — DNS Syslog + NetFlow/IPFIX Dual Collector
=================================================================
Service ini berjalan di Ubuntu VPS dan mendengarkan:
  - UDP 5514  : DNS Syslog dari Mikrotik (nama platform)
  - UDP 2055  : NetFlow v5/v9/IPFIX dari Mikrotik (bytes traffic)

Data digabungkan dan disimpan ke MongoDB collection:
  - peering_eye_dns   : DNS hit per domain per device
  - peering_eye_flows : NetFlow byte counters per platform per device
  - peering_eye_stats : Aggregate per 60 detik (gabungan)

Konfigurasi (environment variables):
  MONGO_URL       : MongoDB connection string (default: mongodb://localhost:27017)
  MONGO_DB        : Database name (default: noc_sentinel)
  DNS_SYSLOG_PORT : UDP port untuk DNS syslog (default: 5514)
  NETFLOW_PORT    : UDP port untuk NetFlow (default: 2055)
  FLUSH_INTERVAL  : Detik antar flush ke MongoDB (default: 60)
"""

import os
import re
import socket
import struct
import threading
import time
import logging
from datetime import datetime, timezone
from collections import defaultdict

from pymongo import MongoClient, UpdateOne

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sentinel-eye")

# ── Config ─────────────────────────────────────────────────────────────────────
MONGO_URL       = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB        = os.getenv("MONGO_DB", "noc_sentinel")
DNS_PORT        = int(os.getenv("DNS_SYSLOG_PORT", "5514"))
NETFLOW_PORT    = int(os.getenv("NETFLOW_PORT", "2055"))
FLUSH_INTERVAL  = int(os.getenv("FLUSH_INTERVAL", "60"))

# ── Platform Map ───────────────────────────────────────────────────────────────
# Format: (regex_pattern, platform_name, icon_emoji, color_hex)
PLATFORM_PATTERNS = [
    # Streaming Video
    (r"(youtube\.com|googlevideo\.com|ytimg\.com|youtu\.be)", "YouTube", "▶", "#FF0000"),
    (r"(netflix\.com|nflxvideo\.net|nflximg\.net|nflxso\.net|nflxext\.com)", "Netflix", "🎬", "#E50914"),
    (r"(tiktok\.com|tiktokv\.com|tiktokcdn\.com|musical\.ly|byteoversea\.com|ibyteimg\.com|snssdk\.com|bytedance\.com)", "TikTok", "🎵", "#010101"),
    (r"(twitch\.tv|twitchsvc\.net|twitchstatic\.com)", "Twitch", "🎮", "#9146FF"),
    (r"(spotify\.com|scdn\.co|spotifycdn\.com)", "Spotify", "🎧", "#1DB954"),
    (r"(disneyplus\.com|bamgrid\.com)", "Disney+", "🎬", "#113CCF"),
    # Social Media
    (r"(facebook\.com|fb\.com|fbcdn\.net|fbsbx\.com|facebook\.net)", "Facebook", "👥", "#1877F2"),
    (r"(instagram\.com|cdninstagram\.com|ig\.me)", "Instagram", "📸", "#E4405F"),
    (r"(twitter\.com|x\.com|twimg\.com|t\.co)", "Twitter/X", "🐦", "#1DA1F2"),
    (r"(pinterest\.com|pinimg\.com)", "Pinterest", "📌", "#E60023"),
    # Messaging
    (r"(whatsapp\.com|whatsapp\.net)", "WhatsApp", "💬", "#25D366"),
    (r"(telegram\.org|t\.me|tdesktop\.com|tlgr\.org|telegram\.me)", "Telegram", "✈", "#2CA5E0"),
    (r"(discord\.com|discordapp\.com|discord\.gg|discordapp\.org|discordapp\.net)", "Discord", "🎮", "#5865F2"),
    (r"(line\.me|line-apps\.com|line-scdn\.net)", "LINE", "💬", "#00C300"),
    # Cloud / Productivity / Tech
    (r"(googleapis\.com|gstatic\.com|google\.com|goo\.gl|googletagmanager|googlesyndication|google-analytics\.com|googlehosted\.com|ggpht\.com)", "Google", "🔍", "#4285F4"),
    (r"(microsoft\.com|msn\.com|live\.com|hotmail\.com|outlook\.com|office\.com|office365|windows\.com|azureedge\.net|live\.net|microsoftonline\.com|skype\.com)", "Microsoft", "🪟", "#0078D4"),
    (r"(icloud\.com|apple\.com|mzstatic\.com|aaplimg\.com|cdn-apple\.com|me\.com)", "Apple/iCloud", "🍎", "#555555"),
    (r"(cloudflare\.com|cloudflare\.net|cloudflare-dns\.com)", "Cloudflare", "☁", "#F38020"),
    (r"(amazon\.com|amazonaws\.com|cloudfront\.net|awsstatic\.com|amazonvideo\.com)", "Amazon/AWS", "📦", "#FF9900"),
    (r"(yahoo\.com|yimg\.com)", "Yahoo", "📰", "#430297"),
    # Global CDNs & Analytics
    (r"(akamai\.net|akamaiedge\.net|akamaitechnologies\.com|edgekey\.net|edgesuite\.net)", "Akamai CDN", "🌍", "#0096D6"),
    (r"(fastly\.net|fastlylb\.net)", "Fastly CDN", "🌍", "#FF282D"),
    (r"(doubleclick\.net|criteo\.com|taboola\.com)", "Ad Networks", "📈", "#FF0055"),
    # Smartphone Home/Telemetry
    (r"(xiaomi\.net|miui\.com|xiaomi\.com)", "Xiaomi", "📱", "#FF6900"),
    (r"(samsung\.com|samsungqbe\.com|secb2b\.com)", "Samsung", "📱", "#1428A0"),
    (r"(coloros\.com|oppomobile\.com|vivo\.com|heytapmobile\.com)", "Oppo/Vivo", "📱", "#006400"),
    # Video Call
    (r"(zoom\.us|zoomgov\.com|zoom\.com)", "Zoom", "📹", "#2D8CFF"),
    # Indonesian Platforms
    (r"(tokopedia\.com|tokopedia\.net|tkpd\.io)", "Tokopedia", "🛒", "#03AC0E"),
    (r"(shopee\.co\.id|seacdn\.com|shopeemobile\.com)", "Shopee", "🛍", "#EE4D2D"),
    (r"(gojek\.com|go\-jek\.com|gotogroup\.com)", "Gojek/GoTo", "🚗", "#00AED6"),
    (r"(grab\.com|grabtaxi\.com|grab\.app)", "Grab", "🚕", "#00B14F"),
    (r"(bukalapak\.com)", "Bukalapak", "🛒", "#E31E52"),
    (r"(traveloka\.com)", "Traveloka", "✈", "#038CC1"),
    (r"(detik\.com|detik\.net)", "Detikcom", "📰", "#0B3189"),
    (r"(kompas\.com|kompasiana\.com)", "Kompas", "📰", "#F26522"),
    (r"(tribunnews\.com|tribunnetwork\.com)", "Tribun", "📰", "#1B5599"),
    # Gaming
    (r"(steampowered\.com|steamcontent\.com|steamcommunity\.com|valve\.net)", "Steam", "🎮", "#1B2838"),
    (r"(riotgames\.com|leagueoflegends\.com|valorant\.com)", "Riot Games", "⚔", "#C6272F"),
    (r"(epicgames\.com|epicgameslauncher\.com|unrealengine\.com)", "Epic Games", "🎮", "#2F2F2F"),
    (r"(roblox\.com|rbxcdn\.com)", "Roblox", "🧱", "#FFFFFF"),
    (r"(garena\.com|garenaplus\.com|garenanow\.com)", "Garena", "🎮", "#F4821F"),
    (r"(ml\.igg\.com|moonton\.com|mobilelegends\.com)", "Mobile Legends", "⚔", "#F5A623"),
    (r"(pubgmobile\.com|tencentgames\.com|igamecj\.com)", "PUBG Mobile", "🔫", "#F5A623"),
]

def match_platform(domain: str) -> tuple[str, str, str]:
    """Return (platform_name, icon, color) matching a domain."""
    d = domain.lower().strip(".")
    for pattern, name, icon, color in PLATFORM_PATTERNS:
        if re.search(pattern, d):
            return name, icon, color
    return "Others", "🌐", "#64748b"


# ── MongoDB helper ─────────────────────────────────────────────────────────────
def get_db():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    return client[MONGO_DB]


# ── In-memory accumulators (flushed every FLUSH_INTERVAL seconds) ──────────────
dns_acc   = defaultdict(lambda: defaultdict(int))   # {(device_id, platform) : hits}
flow_acc  = defaultdict(lambda: defaultdict(int))   # {(device_id, platform) : bytes}
dns_names = {}                                       # (device_id, platform) -> (icon, color)
acc_lock  = threading.Lock()

# IP → platform cache (populated from DNS syslog, used by NetFlow)
ip_platform_cache: dict[str, str] = {}   # dst_ip → platform_name
cache_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
# THREAD 1 — DNS SYSLOG LISTENER (UDP:5514)
# ═══════════════════════════════════════════════════════════════════════════════

DNS_LOG_PATTERNS = [
    # RouterOS logging format: "dns query from 192.168.1.1: youtube.com"
    re.compile(r"query\s+from\s+[\d.]+:\s+([\w.\-]+)", re.IGNORECASE),
    # Alternative: "dns,packet youtube.com A"
    re.compile(r"dns.*?\s+([\w.\-]+)\s+(?:A|AAAA|CNAME)", re.IGNORECASE),
    # Simple: just a domain somewhere in the line
    re.compile(r"\b((?:[a-z0-9\-]+\.)+(?:com|net|org|id|io|co|tv|me|app|dev))\b", re.IGNORECASE),
]

def parse_dns_syslog(raw: bytes, sender_ip: str) -> dict | None:
    """Parse a RouterOS syslog line and extract device + domain info."""
    try:
        msg = raw.decode("utf-8", errors="replace").strip()
    except Exception:
        return None

    domain = None
    for pat in DNS_LOG_PATTERNS:
        m = pat.search(msg)
        if m:
            domain = m.group(1).lower().strip(".")
            break

    if not domain or len(domain) < 4:
        return None

    # Exclude very common infra domains that would pollute stats
    skip = ("in-addr.arpa", "local", "localhost", "arpa", "wpad")
    if any(domain.endswith(s) for s in skip):
        return None

    platform, icon, color = match_platform(domain)

    # Identify device by sender IP (Mikrotik IP address)
    device_id = sender_ip  # Will be enriched from DB lookup periodically

    return {
        "device_id": device_id,
        "domain": domain,
        "platform": platform,
        "icon": icon,
        "color": color,
    }


def dns_syslog_listener():
    """UDP listener for DNS syslog on DNS_PORT."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", DNS_PORT))
    sock.settimeout(5.0)

    logger.info(f"DNS Syslog listener started on UDP:{DNS_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            sender_ip = addr[0]
            result = parse_dns_syslog(data, sender_ip)
            if result:
                key = (result["device_id"], result["platform"])
                with acc_lock:
                    dns_acc[key]["hits"] += 1
                    dns_names[key] = (result["icon"], result["color"])
                    dns_acc[key]["domain_" + result["domain"][:64]] += 1
                # Cache: any IP we know is Google's CDN → YouTube, etc.
                # Will be updated by NetFlow enrichment
        except socket.timeout:
            continue
        except Exception as e:
            logger.warning(f"DNS syslog parse error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# THREAD 2 — NETFLOW v5/v9 LISTENER (UDP:2055)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_netflow_v5(data: bytes, sender_ip: str) -> list[dict]:
    """Parse NetFlow v5 packet. Returns list of flow records."""
    records = []
    if len(data) < 24:
        return records
    try:
        header = struct.unpack("!HHIIIIHH", data[:24])
        version, count = header[0], header[1]
        if version != 5:
            return records

        FLOW_SIZE = 48
        for i in range(count):
            offset = 24 + i * FLOW_SIZE
            if offset + FLOW_SIZE > len(data):
                break
            flow = data[offset:offset + FLOW_SIZE]
            fields = struct.unpack("!4s4s4sHHIIIIHHxBBBHHBB", flow)
            src_ip   = socket.inet_ntoa(fields[0])
            dst_ip   = socket.inet_ntoa(fields[1])
            packets  = fields[7]
            octets   = fields[8]   # bytes

            # Check if we know what platform this dst_ip is
            with cache_lock:
                platform = ip_platform_cache.get(dst_ip)

            if platform is None:
                # Try reverse lookup (optional; skip to keep it fast)
                platform = "Others"

            records.append({
                "device_id": sender_ip,
                "src_ip": src_ip,
                "dst_ip": dst_ip,
                "bytes": octets,
                "packets": packets,
                "platform": platform,
            })
    except Exception as e:
        logger.debug(f"NetFlow v5 parse error: {e}")
    return records


def parse_netflow_v9_or_ipfix(data: bytes, sender_ip: str) -> list[dict]:
    """
    Simplified NetFlow v9 / IPFIX parser.
    Full template handling is complex; here we do best-effort extraction.
    For production consider using the 'netflow' or 'ipfixcol2' library.
    """
    records = []
    if len(data) < 20:
        return records
    try:
        version = struct.unpack("!H", data[:2])[0]
        if version not in (9, 10):
            return records
        # For v9/IPFIX we just look for recognizable 4-byte IP octets
        # This is "good enough" for byte counting per device
        # Full implementation requires template cache which is stateful
        # Using placeholder: count total bytes and attribute to "Others" by flow
        count_bytes = len(data)
        records.append({
            "device_id": sender_ip,
            "bytes": count_bytes,
            "platform": "Others",  # Without template, we can't classify
        })
    except Exception as e:
        logger.debug(f"NetFlow v9/IPFIX parse error: {e}")
    return records


def netflow_listener():
    """UDP listener for NetFlow on NETFLOW_PORT."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", NETFLOW_PORT))
    sock.settimeout(5.0)

    logger.info(f"NetFlow listener started on UDP:{NETFLOW_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(65535)
            sender_ip = addr[0]

            version = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else 0
            if version == 5:
                flows = parse_netflow_v5(data, sender_ip)
            elif version in (9, 10):
                flows = parse_netflow_v9_or_ipfix(data, sender_ip)
            else:
                continue

            with acc_lock:
                for flow in flows:
                    key = (flow["device_id"], flow["platform"])
                    flow_acc[key]["bytes"] += flow.get("bytes", 0)
                    flow_acc[key]["packets"] += flow.get("packets", 0)

        except socket.timeout:
            continue
        except Exception as e:
            logger.warning(f"NetFlow listener error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# THREAD 3 — FLUSH TO MONGODB (every FLUSH_INTERVAL)
# ═══════════════════════════════════════════════════════════════════════════════

# Cache to enrich device_id (sender IP → device info) from noc_sentinel DB
device_cache: dict[str, dict] = {}
device_cache_ts = 0.0

def refresh_device_cache(db):
    """Refresh device IP → {id, name} mapping from devices collection."""
    global device_cache, device_cache_ts
    now = time.time()
    if now - device_cache_ts < 300:  # Refresh every 5 min
        return
    try:
        devices = list(db.devices.find({}, {"_id": 0, "id": 1, "name": 1, "ip_address": 1}))
        new_cache = {}
        for d in devices:
            ip = d.get("ip_address", "").split(":")[0].strip()
            if ip:
                new_cache[ip] = {"id": d.get("id", ip), "name": d.get("name", ip)}
        device_cache = new_cache
        device_cache_ts = now
        logger.info(f"Device cache refreshed: {len(device_cache)} devices")
    except Exception as e:
        logger.warning(f"Device cache refresh failed: {e}")


def refresh_ip_cache(db):
    """Refresh dst_ip -> platform mapping from the DB populated by sentinel_bgp."""
    global ip_platform_cache
    try:
        docs = list(db.peering_eye_ips.find({}, {"_id": 0, "ip": 1, "platform": 1}))
        new_cache = {d["ip"]: d["platform"] for d in docs if "ip" in d}
        with cache_lock:
            ip_platform_cache = new_cache
        logger.debug(f"IP platform cache refreshed: {len(new_cache)} IPs")
    except Exception as e:
        logger.warning(f"IP platform cache refresh failed: {e}")

def flush_to_mongo():
    """Periodic flush: combine dns_acc + flow_acc → MongoDB."""
    db = get_db()
    logger.info(f"MongoDB flush loop started (interval={FLUSH_INTERVAL}s)")

    while True:
        time.sleep(FLUSH_INTERVAL)
        try:
            refresh_device_cache(db)
            refresh_ip_cache(db)

            with acc_lock:
                dns_snapshot  = {k: dict(v) for k, v in dns_acc.items()}
                flow_snapshot = {k: dict(v) for k, v in flow_acc.items()}
                names_snapshot = dict(dns_names)
                dns_acc.clear()
                flow_acc.clear()

            if not dns_snapshot and not flow_snapshot:
                continue

            now_iso = datetime.now(timezone.utc).isoformat()

            # Collect all unique (device_id, platform) keys
            all_keys = set(dns_snapshot.keys()) | set(flow_snapshot.keys())

            ops = []
            for (raw_device_id, platform) in all_keys:
                # Enrich device_id using device cache
                dev_info = device_cache.get(raw_device_id, {})
                device_id   = dev_info.get("id",   raw_device_id)
                device_name = dev_info.get("name", raw_device_id)

                dns_data  = dns_snapshot.get((raw_device_id, platform), {})
                flow_data = flow_snapshot.get((raw_device_id, platform), {})
                icon, color = names_snapshot.get((raw_device_id, platform), ("🌐", "#64748b"))

                hits       = dns_data.get("hits", 0)
                bytes_val  = flow_data.get("bytes", 0)
                packets    = flow_data.get("packets", 0)

                # Top domains from dns_data keys that start with "domain_"
                domains = {
                    k.replace("domain_", ""): v
                    for k, v in dns_data.items()
                    if k.startswith("domain_")
                }

                doc = {
                    "device_id":   device_id,
                    "device_name": device_name,
                    "platform":    platform,
                    "icon":        icon,
                    "color":       color,
                    "hits":        hits,
                    "bytes":       bytes_val,
                    "packets":     packets,
                    "top_domains": domains,
                    "timestamp":   now_iso,
                }

                ops.append(
                    UpdateOne(
                        {
                            "device_id": device_id,
                            "platform":  platform,
                            "timestamp": now_iso,
                        },
                        {"$set": doc},
                        upsert=True,
                    )
                )

            if ops:
                db.peering_eye_stats.bulk_write(ops)
                logger.info(f"Flushed {len(ops)} platform records to MongoDB")

            # Cleanup old records (keep 30 days)
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            db.peering_eye_stats.delete_many({"timestamp": {"$lt": cutoff}})

        except Exception as e:
            logger.error(f"MongoDB flush error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("  Sentinel Peering-Eye Collector v1.0")
    logger.info(f"  DNS Syslog  : UDP:{DNS_PORT}")
    logger.info(f"  NetFlow     : UDP:{NETFLOW_PORT}")
    logger.info(f"  MongoDB     : {MONGO_URL}/{MONGO_DB}")
    logger.info(f"  Flush every : {FLUSH_INTERVAL}s")
    logger.info("=" * 60)

    # Verify DB connection
    try:
        db = get_db()
        db.command("ping")
        logger.info("MongoDB connection OK")

        # Ensure indexes for performance
        db.peering_eye_stats.create_index([("device_id", 1), ("timestamp", -1)])
        db.peering_eye_stats.create_index([("platform", 1)])
        db.peering_eye_stats.create_index([("timestamp", -1)])
        logger.info("MongoDB indexes ensured")
    except Exception as e:
        logger.error(f"MongoDB connection FAILED: {e}")
        logger.error("Make sure MongoDB is running and MONGO_URL is set correctly.")
        raise SystemExit(1)

    # Start listener threads
    threads = [
        threading.Thread(target=dns_syslog_listener, name="dns-listener", daemon=True),
        threading.Thread(target=netflow_listener,    name="netflow-listener", daemon=True),
        threading.Thread(target=flush_to_mongo,      name="mongo-flusher", daemon=True),
    ]
    for t in threads:
        t.start()
        logger.info(f"Thread '{t.name}' started")

    logger.info("Sentinel Peering-Eye is running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
            alive = [t.name for t in threads if t.is_alive()]
            logger.info(f"Heartbeat — active threads: {alive}")
    except KeyboardInterrupt:
        logger.info("Shutting down Sentinel Peering-Eye...")


if __name__ == "__main__":
    main()
