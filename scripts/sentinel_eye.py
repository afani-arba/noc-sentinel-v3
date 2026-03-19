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
    # Clandestine / Restricted
    (r"(sbobet|m88|88tangkas|slot88|pragmaticplay|habanero|joker123|spadegaming|maxbet|cmd368|pgsoft)", "Judi Online", "🎰", "#be123c"),
    (r"(pornhub\.com|xvideos\.com|xnxx\.com|redtube\.com|xhamster\.com|brazzers\.com|chaturbate\.com|onlyfans\.com)", "Situs Dewasa", "🔞", "#be185d"),
    # Streaming Video
    (r"(youtube\.com|googlevideo\.com|ytimg\.com|youtu\.be)", "YouTube", "▶", "#ef4444"),
    (r"(netflix\.com|nflxvideo\.net|nflximg\.net|nflxso\.net|nflxext\.com)", "Netflix", "🎬", "#f43f5e"),
    (r"(tiktok\.com|tiktokv\.com|tiktokcdn\.com|musical\.ly|byteoversea\.com|ibyteimg\.com|snssdk\.com|bytedance\.com)", "TikTok", "🎵", "#ec4899"),
    (r"(twitch\.tv|twitchsvc\.net|twitchstatic\.com)", "Twitch", "🎮", "#a855f7"),
    (r"(spotify\.com|scdn\.co|spotifycdn\.com)", "Spotify", "🎧", "#22c55e"),
    (r"(disneyplus\.com|bamgrid\.com)", "Disney+", "🎬", "#3b82f6"),
    # Social Media
    (r"(facebook\.com|fb\.com|fbcdn\.net|fbsbx\.com|facebook\.net)", "Facebook", "👥", "#3b82f6"),
    (r"(instagram\.com|cdninstagram\.com|ig\.me)", "Instagram", "📸", "#d946ef"),
    (r"(twitter\.com|x\.com|twimg\.com|t\.co)", "Twitter/X", "🐦", "#e2e8f0"),
    (r"(pinterest\.com|pinimg\.com)", "Pinterest", "📌", "#ef4444"),
    # Messaging
    (r"(whatsapp\.com|whatsapp\.net)", "WhatsApp", "💬", "#10b981"),
    (r"(telegram\.org|t\.me|tdesktop\.com|tlgr\.org|telegram\.me)", "Telegram", "✈", "#0ea5e9"),
    (r"(discord\.com|discordapp\.com|discord\.gg|discordapp\.org|discordapp\.net)", "Discord", "🎮", "#6366f1"),
    (r"(line\.me|line-apps\.com|line-scdn\.net)", "LINE", "💬", "#22c55e"),
    # Cloud / Productivity / Tech
    (r"(googleapis\.com|gstatic\.com|google\.com|goo\.gl|googletagmanager|googlesyndication|google-analytics\.com|googlehosted\.com|ggpht\.com)", "Google", "🔍", "#60a5fa"),
    (r"(microsoft\.com|msn\.com|live\.com|hotmail\.com|outlook\.com|office\.com|office365|windows\.com|azureedge\.net|live\.net|microsoftonline\.com|skype\.com)", "Microsoft", "🪟", "#38bdf8"),
    (r"(icloud\.com|apple\.com|mzstatic\.com|aaplimg\.com|cdn-apple\.com|me\.com)", "Apple/iCloud", "🍎", "#94a3b8"),
    (r"(cloudflare\.com|cloudflare\.net|cloudflare-dns\.com)", "Cloudflare", "☁", "#f97316"),
    (r"(amazon\.com|amazonaws\.com|cloudfront\.net|awsstatic\.com|amazonvideo\.com)", "Amazon/AWS", "📦", "#f59e0b"),
    (r"(yahoo\.com|yimg\.com)", "Yahoo", "📰", "#8b5cf6"),
    # Global CDNs & Analytics
    (r"(akamai\.net|akamaiedge\.net|akamaitechnologies\.com|edgekey\.net|edgesuite\.net)", "Akamai CDN", "🌍", "#14b8a6"),
    (r"(fastly\.net|fastlylb\.net)", "Fastly CDN", "🌍", "#f43f5e"),
    (r"(doubleclick\.net|criteo\.com|taboola\.com)", "Ad Networks", "📈", "#f472b6"),
    # Smartphone Home/Telemetry
    (r"(xiaomi\.net|miui\.com|xiaomi\.com)", "Xiaomi", "📱", "#f97316"),
    (r"(samsung\.com|samsungqbe\.com|secb2b\.com)", "Samsung", "📱", "#3b82f6"),
    (r"(coloros\.com|oppomobile\.com|vivo\.com|heytapmobile\.com)", "Oppo/Vivo", "📱", "#22c55e"),
    # Video Call
    (r"(zoom\.us|zoomgov\.com|zoom\.com)", "Zoom", "📹", "#3b82f6"),
    # Indonesian Platforms
    (r"(tokopedia\.com|tokopedia\.net|tkpd\.io)", "Tokopedia", "🛒", "#22c55e"),
    (r"(shopee\.co\.id|seacdn\.com|shopeemobile\.com)", "Shopee", "🛍", "#f97316"),
    (r"(gojek\.com|go\-jek\.com|gotogroup\.com)", "Gojek/GoTo", "🚗", "#10b981"),
    (r"(grab\.com|grabtaxi\.com|grab\.app)", "Grab", "🚕", "#22c55e"),
    (r"(bukalapak\.com)", "Bukalapak", "🛒", "#e11d48"),
    (r"(traveloka\.com)", "Traveloka", "✈", "#0ea5e9"),
    (r"(detik\.com|detik\.net)", "Detikcom", "📰", "#1d4ed8"),
    (r"(kompas\.com|kompasiana\.com)", "Kompas", "📰", "#ea580c"),
    (r"(tribunnews\.com|tribunnetwork\.com)", "Tribun", "📰", "#1e3a8a"),
    # Gaming
    (r"(steampowered\.com|steamcontent\.com|steamcommunity\.com|valve\.net)", "Steam", "🎮", "#334155"),
    (r"(riotgames\.com|leagueoflegends\.com|valorant\.com)", "Riot Games", "⚔", "#e11d48"),
    (r"(epicgames\.com|epicgameslauncher\.com|unrealengine\.com)", "Epic Games", "🎮", "#475569"),
    (r"(roblox\.com|rbxcdn\.com)", "Roblox", "🧱", "#f8fafc"),
    (r"(garena\.com|garenaplus\.com|garenanow\.com)", "Garena", "🎮", "#ea580c"),
    (r"(ml\.igg\.com|moonton\.com|mobilelegends\.com)", "Mobile Legends", "⚔", "#eab308"),
    (r"(pubgmobile\.com|tencentgames\.com|igamecj\.com)", "PUBG Mobile", "🔫", "#f59e0b"),
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

def parse_dns_syslog(raw: bytes, sender_ip: str) -> dict | None:
    """Parse a RouterOS syslog line and extract device + domain info + client IP."""
    try:
        msg = raw.decode("utf-8", errors="replace").strip()
    except Exception:
        return None

    # Step 1: Tarik Domain apa saja yang valid (com/net/org/id dll)
    domain_match = re.search(r"\b((?:[a-z0-9\-]+\.)+(?:com|net|org|id|io|co|tv|me|app|dev|biz|info))\b", msg, re.IGNORECASE)
    if not domain_match:
        return None
    
    domain = domain_match.group(1).lower().strip(".")

    # Step 2: Tarik IP Klien jika ada teks "from 192.x.x.x" (khas Mikrotik query log)
    client_ip = None
    ip_match = re.search(r"from\s+([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})", msg, re.IGNORECASE)
    if ip_match:
        client_ip = ip_match.group(1)

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
        "client_ip": client_ip,
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
                    if result.get("client_ip"):
                        dns_acc[key]["client_" + result["client_ip"]] += 1
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
            fields = struct.unpack("!4s4s4sHHIIIIHHxBBBHHBBxx", flow)
            src_ip   = socket.inet_ntoa(fields[0])
            dst_ip   = socket.inet_ntoa(fields[1])
            packets  = fields[5]
            octets   = fields[6]   # bytes

            # SANITY CHECK: Cegah Bug Mikrotik (ROS v6/v7) melempar traffic Terabyte palsu!
            # Batas logis MTU adalah 1500 byte per paket. Jika lebih, berarti angka octets cacat (wrapped int).
            if octets > packets * 1600:
                octets = packets * 1000  # Fallback ke rata-rata 1KB per paket
            
            if octets > 500_000_000:     # Limit absolut: 500 MB per flow record (mencegah spike gila)
                octets = 500_000_000

            # Check if we know what platform this dst_ip or src_ip belongs to
            with cache_lock:
                platform = ip_platform_cache.get(dst_ip)
                if not platform:
                    platform = ip_platform_cache.get(src_ip)

            if not platform:
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
    
    # Run initial cache population before entering the sleep loop
    refresh_device_cache(db)
    refresh_ip_cache(db)

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
                clients = {
                    k.replace("client_", ""): v
                    for k, v in dns_data.items()
                    if k.startswith("client_")
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
                    "top_clients": clients,
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
