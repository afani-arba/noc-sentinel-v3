"""
Sentinel Peering-Eye API Router
================================
Endpoints untuk membaca data dari collection:
  - peering_eye_stats      : DNS + NetFlow aggregate per platform per device
  - peering_eye_bgp_status : BGP peer status snapshot

Mount prefix: /api/peering-eye
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from core.db import get_db
from core.auth import get_current_user

router = APIRouter(prefix="/peering-eye", tags=["Peering Eye"])

# ─── Platform colors & icons (fallback jika kolom tidak ada di DB) ────────────
PLATFORM_META = {
    "Judi Online":  {"icon": "🎰", "color": "#be123c"},
    "Situs Dewasa": {"icon": "🔞", "color": "#be185d"},
    "YouTube":      {"icon": "▶",  "color": "#ef4444"},
    "Netflix":      {"icon": "🎬", "color": "#f43f5e"},
    "TikTok":       {"icon": "🎵", "color": "#ec4899"},
    "Twitch":       {"icon": "🎮", "color": "#a855f7"},
    "Spotify":      {"icon": "🎧", "color": "#22c55e"},
    "Disney+":      {"icon": "🎬", "color": "#3b82f6"},
    "Facebook":     {"icon": "👥", "color": "#3b82f6"},
    "Instagram":    {"icon": "📸", "color": "#d946ef"},
    "Twitter/X":    {"icon": "🐦", "color": "#e2e8f0"},
    "Pinterest":    {"icon": "📌", "color": "#ef4444"},
    "WhatsApp":     {"icon": "💬", "color": "#10b981"},
    "Telegram":     {"icon": "✈",  "color": "#0ea5e9"},
    "Discord":      {"icon": "🎮", "color": "#6366f1"},
    "LINE":         {"icon": "💬", "color": "#22c55e"},
    "Google":       {"icon": "🔍", "color": "#60a5fa"},
    "Microsoft":    {"icon": "🪟", "color": "#38bdf8"},
    "Apple/iCloud": {"icon": "🍎", "color": "#94a3b8"},
    "Cloudflare":   {"icon": "☁",  "color": "#f97316"},
    "Amazon/AWS":   {"icon": "📦", "color": "#f59e0b"},
    "Yahoo":        {"icon": "📰", "color": "#8b5cf6"},
    "Akamai CDN":   {"icon": "🌍", "color": "#14b8a6"},
    "Fastly CDN":   {"icon": "🌍", "color": "#f43f5e"},
    "Ad Networks":  {"icon": "📈", "color": "#f472b6"},
    "Xiaomi":       {"icon": "📱", "color": "#f97316"},
    "Samsung":      {"icon": "📱", "color": "#3b82f6"},
    "Oppo/Vivo":    {"icon": "📱", "color": "#22c55e"},
    "Zoom":         {"icon": "📹", "color": "#3b82f6"},
    "Tokopedia":    {"icon": "🛒", "color": "#22c55e"},
    "Shopee":       {"icon": "🛍", "color": "#f97316"},
    "Gojek/GoTo":   {"icon": "🚗", "color": "#10b981"},
    "Grab":         {"icon": "🚕", "color": "#22c55e"},
    "Bukalapak":    {"icon": "🛒", "color": "#e11d48"},
    "Traveloka":    {"icon": "✈",  "color": "#0ea5e9"},
    "Detikcom":     {"icon": "📰", "color": "#1d4ed8"},
    "Kompas":       {"icon": "📰", "color": "#ea580c"},
    "Tribun":       {"icon": "📰", "color": "#1e3a8a"},
    "Steam":        {"icon": "🎮", "color": "#334155"},
    "Riot Games":   {"icon": "⚔",  "color": "#e11d48"},
    "Epic Games":   {"icon": "🎮", "color": "#475569"},
    "Roblox":       {"icon": "🧱", "color": "#f8fafc"},
    "Garena":       {"icon": "🎮", "color": "#ea580c"},
    "Mobile Legends":{"icon": "⚔", "color": "#eab308"},
    "PUBG Mobile":  {"icon": "🔫", "color": "#f59e0b"},
    "Others":       {"icon": "🌐", "color": "#64748b"},
}


def fmt_bytes(b: int) -> str:
    if b >= 1e9:
        return f"{b/1e9:.2f} GB"
    if b >= 1e6:
        return f"{b/1e6:.2f} MB"
    if b >= 1e3:
        return f"{b/1e3:.1f} KB"
    return f"{b} B"


def range_to_start(range_str: str) -> str:
    """Convert range string (1h/6h/12h/24h/7d/30d) to ISO start timestamp."""
    hours_map = {"1h": 1, "6h": 6, "12h": 12, "24h": 24, "7d": 168, "30d": 720}
    hours = hours_map.get(range_str, 24)
    start = datetime.now(timezone.utc) - timedelta(hours=hours)
    return start.isoformat()


# ─── Endpoint: List Device IDs yang ada datanya ──────────────────────────────
@router.get("/devices")
async def peering_eye_devices(user=Depends(get_current_user)):
    """Return list of devices that have Peering-Eye data."""
    db = get_db()
    pipeline = [
        {"$group": {
            "_id": "$device_id",
            "device_name": {"$last": "$device_name"},
            "last_seen": {"$max": "$timestamp"},
            "total_hits": {"$sum": "$hits"},
        }},
        {"$sort": {"total_hits": -1}},
    ]
    docs = await db.peering_eye_stats.aggregate(pipeline).to_list(100)
    return [
        {
            "device_id":   d["_id"],
            "device_name": d.get("device_name", d["_id"]),
            "last_seen":   d.get("last_seen"),
            "total_hits":  d.get("total_hits", 0),
        }
        for d in docs
    ]


# ─── Endpoint: Stats — aggregate per platform ─────────────────────────────────
@router.get("/stats")
async def peering_eye_stats(
    device_id: str = "",
    range: str = "24h",
    user=Depends(get_current_user),
):
    """Aggregate platform statistics (hits + bytes) for a device or all devices."""
    db = get_db()
    start = range_to_start(range)

    match: dict = {"timestamp": {"$gte": start}}
    if device_id and device_id != "all":
        match["device_id"] = device_id

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$platform",
            "icon":  {"$last": "$icon"},
            "color": {"$last": "$color"},
            "hits":  {"$sum": "$hits"},
            "bytes": {"$sum": "$bytes"},
            "device_name": {"$last": "$device_name"},
        }},
        {"$sort": {"hits": -1}},
    ]

    docs = await db.peering_eye_stats.aggregate(pipeline).to_list(100)

    total_hits  = sum(d.get("hits", 0) for d in docs)
    total_bytes = sum(d.get("bytes", 0) for d in docs)

    platforms = []
    for d in docs:
        p = d["_id"]
        meta = PLATFORM_META.get(p, {"icon": "🌐", "color": "#64748b"})
        hits  = d.get("hits", 0)
        bytes_val = d.get("bytes", 0)
        platforms.append({
            "platform":    p,
            "icon":        d.get("icon") or meta["icon"],
            "color":       d.get("color") or meta["color"],
            "hits":        hits,
            "bytes":       bytes_val,
            "bytes_fmt":   fmt_bytes(bytes_val),
            "pct_hits":    round(hits / total_hits * 100, 1) if total_hits else 0,
            "pct_bytes":   round(bytes_val / total_bytes * 100, 1) if total_bytes else 0,
        })

    return {
        "device_id":   device_id or "all",
        "range":       range,
        "total_hits":  total_hits,
        "total_bytes": total_bytes,
        "total_bytes_fmt": fmt_bytes(total_bytes),
        "platform_count": len(platforms),
        "platforms":   platforms,
    }


# ─── Endpoint: Timeline — time-series per platform ────────────────────────────
@router.get("/timeline")
async def peering_eye_timeline(
    device_id: str = "",
    platform:  str = "",
    range:     str = "12h",
    user=Depends(get_current_user),
):
    """Time-series data for charting (bucket per hour or 10 min)."""
    db = get_db()
    start = range_to_start(range)

    match: dict = {"timestamp": {"$gte": start}}
    if device_id and device_id != "all":
        match["device_id"] = device_id
    if platform and platform != "all":
        match["platform"] = platform

    # Bucket size: 1h for long ranges, 10min for short ranges
    bucket_ms = 600_000 if range in ("1h", "6h", "12h") else 3_600_000

    pipeline = [
        {"$match": match},
        {"$addFields": {
            "ts_ms": {"$toLong": {"$dateFromString": {"dateString": "$timestamp"}}},
        }},
        {"$group": {
            "_id": {
                "bucket":   {"$subtract": ["$ts_ms", {"$mod": ["$ts_ms", bucket_ms]}]},
                "platform": "$platform",
            },
            "hits":  {"$sum": "$hits"},
            "bytes": {"$sum": "$bytes"},
            "icon":  {"$last": "$icon"},
            "color": {"$last": "$color"},
        }},
        {"$sort": {"_id.bucket": 1}},
    ]

    docs = await db.peering_eye_stats.aggregate(pipeline).to_list(5000)

    # Reshape: { time: [{ platform, hits, bytes }] }
    time_map: dict = {}
    for d in docs:
        bucket_ms_val = d["_id"]["bucket"]
        if not isinstance(bucket_ms_val, (int, float)):
            continue
        utc = datetime.fromtimestamp(bucket_ms_val / 1000, tz=timezone.utc)
        local = utc + timedelta(hours=7)  # WIB
        label = local.strftime("%H:%M" if range in ("1h","6h","12h") else "%d/%m %H:%M")

        p = d["_id"]["platform"]
        meta = PLATFORM_META.get(p, {"icon": "🌐", "color": "#64748b"})

        if label not in time_map:
            time_map[label] = {"time": label}
        time_map[label][p] = {
            "hits": d.get("hits", 0),
            "bytes": d.get("bytes", 0),
            "icon": d.get("icon") or meta["icon"],
            "color": d.get("color") or meta["color"],
        }

    return {
        "device_id": device_id or "all",
        "range":     range,
        "platform":  platform or "all",
        "data":      list(time_map.values()),
    }


# ─── Endpoint: Top Domains ────────────────────────────────────────────────────
@router.get("/top-domains")
async def peering_eye_top_domains(
    device_id: str = "",
    range:     str = "24h",
    limit:     int = 20,
    user=Depends(get_current_user),
):
    """Return top raw domains ordered by hit count."""
    db = get_db()
    start = range_to_start(range)

    match: dict = {"timestamp": {"$gte": start}}
    if device_id and device_id != "all":
        match["device_id"] = device_id

    docs = await db.peering_eye_stats.find(
        match, {"_id": 0, "top_domains": 1, "platform": 1, "icon": 1, "color": 1}
    ).to_list(5000)

    domain_agg: dict = defaultdict(lambda: {"hits": 0, "platform": "", "icon": "🌐", "color": "#64748b"})
    for doc in docs:
        td = doc.get("top_domains") or {}
        for domain, hits in td.items():
            domain_agg[domain]["hits"] += hits
            if not domain_agg[domain]["platform"]:
                domain_agg[domain]["platform"] = doc.get("platform", "Others")
                domain_agg[domain]["icon"]     = doc.get("icon", "🌐")
                domain_agg[domain]["color"]    = doc.get("color", "#64748b")

    sorted_domains = sorted(domain_agg.items(), key=lambda x: x[1]["hits"], reverse=True)[:limit]

    return {
        "device_id": device_id or "all",
        "range":     range,
        "domains": [
            {
                "domain":   domain,
                "hits":     info["hits"],
                "platform": info["platform"],
                "icon":     info["icon"],
                "color":    info["color"],
            }
            for domain, info in sorted_domains
        ]
    }


# ─── Endpoint: BGP Status ────────────────────────────────────────────────────
@router.get("/bgp/status")
async def bgp_status(user=Depends(get_current_user)):
    """Return current BGP peer status from MongoDB snapshot."""
    db = get_db()
    docs = await db.peering_eye_bgp_status.find(
        {}, {"_id": 0}
    ).to_list(200)

    # Augment with human-readable uptime
    for d in docs:
        uptime_s = d.get("uptime_sec", 0)
        if uptime_s:
            days  = uptime_s // 86400
            hrs   = (uptime_s % 86400) // 3600
            mins  = (uptime_s % 3600) // 60
            d["uptime_fmt"] = f"{days}d {hrs}h {mins}m" if days else f"{hrs}h {mins}m"
        else:
            d["uptime_fmt"] = "—"

    established = sum(1 for d in docs if d.get("state") == "ESTABLISHED")
    return {
        "peers":       docs,
        "total":       len(docs),
        "established": established,
        "updated_at":  docs[0].get("updated_at") if docs else None,
    }


# ─── Endpoint: BGP Manual Sync trigger ───────────────────────────────────────
@router.post("/bgp/sync")
async def bgp_sync(user=Depends(get_current_user)):
    """Trigger immediate BGP peer sync (writes a flag to DB for sentinel_bgp.py)."""
    db = get_db()
    await db.peering_eye_control.update_one(
        {"_id": "bgp_sync"},
        {"$set": {"trigger": True, "requested_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"status": "ok", "message": "BGP sync requested — sentinel_bgp.py will process within 30 seconds"}


# ─── Endpoint: Ingest — receive data from sentinel_eye.py ────────────────────
@router.post("/ingest")
async def peering_eye_ingest(payload: dict, user=Depends(get_current_user)):
    """
    Receive pre-aggregated data from sentinel_eye.py running on the Ubuntu VPS.
    This allows the collector to push data in batch.
    """
    db = get_db()
    required = ["device_id", "platform"]
    for f in required:
        if f not in payload:
            raise HTTPException(400, f"Missing field: {f}")

    now = datetime.now(timezone.utc).isoformat()
    platform = payload["platform"]
    meta = PLATFORM_META.get(platform, {"icon": "🌐", "color": "#64748b"})

    doc = {
        "device_id":   payload["device_id"],
        "device_name": payload.get("device_name", payload["device_id"]),
        "platform":    platform,
        "icon":        payload.get("icon", meta["icon"]),
        "color":       payload.get("color", meta["color"]),
        "hits":        int(payload.get("hits", 0)),
        "bytes":       int(payload.get("bytes", 0)),
        "packets":     int(payload.get("packets", 0)),
        "top_domains": payload.get("top_domains", {}),
        "timestamp":   payload.get("timestamp", now),
    }

    await db.peering_eye_stats.insert_one(doc)
    return {"status": "ok", "inserted": 1}


# ─── Endpoint: Summary for header cards ──────────────────────────────────────
@router.get("/summary")
async def peering_eye_summary(
    device_id: str = "",
    range:     str = "24h",
    user=Depends(get_current_user),
):
    """Quick summary: total hits, top platform, unique domains, bytes."""
    db = get_db()
    start = range_to_start(range)

    match: dict = {"timestamp": {"$gte": start}}
    if device_id and device_id != "all":
        match["device_id"] = device_id

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id":         "$platform",
            "hits":        {"$sum": "$hits"},
            "bytes":       {"$sum": "$bytes"},
            "domain_count": {"$sum": {"$size": {"$objectToArray": {"$ifNull": ["$top_domains", {}]}}}},
        }},
        {"$sort": {"hits": -1}},
    ]

    docs = await db.peering_eye_stats.aggregate(pipeline).to_list(100)
    if not docs:
        return {
            "total_hits": 0, "total_bytes": 0, "total_bytes_fmt": "0 B",
            "top_platform": "—", "top_platform_icon": "🌐",
            "unique_platforms": 0, "unique_domains": 0,
        }

    total_hits   = sum(d["hits"] for d in docs)
    total_bytes  = sum(d["bytes"] for d in docs)
    total_domains = sum(d["domain_count"] for d in docs)
    top = docs[0]
    top_meta = PLATFORM_META.get(top["_id"], {"icon": "🌐"})

    return {
        "total_hits":       total_hits,
        "total_bytes":      total_bytes,
        "total_bytes_fmt":  fmt_bytes(total_bytes),
        "top_platform":     top["_id"],
        "top_platform_icon": top_meta["icon"],
        "top_platform_hits": top["hits"],
        "unique_platforms": len(docs),
        "unique_domains":   total_domains,
    }
