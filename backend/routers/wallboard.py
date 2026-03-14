"""
Wallboard router: NOC Wall Display endpoints.
Provides aggregated device status, live metrics, and event ticker
for NOC wall display screens.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from core.db import get_db
from core.auth import get_current_user
from mikrotik_api import get_api_client

router = APIRouter(prefix="/wallboard", tags=["wallboard"])
logger = logging.getLogger(__name__)


async def _fetch_session_counts(device: dict) -> tuple[int, int]:
    """
    Fetch PPPoE active count + Hotspot active count langsung dari MikroTik.
    Sama dengan cara kerja pppoe.py yang sudah terbukti bekerja.
    Timeout 6 detik agar tidak memperlambat wallboard response.
    Returns (pppoe_count, hotspot_count).
    """
    if device.get("status") != "online":
        return (
            device.get("pppoe_active", 0),
            device.get("hotspot_active", 0),
        )
    try:
        mt = get_api_client(device)

        async def safe_count(coro) -> int:
            try:
                result = await asyncio.wait_for(coro, timeout=6)
                return len(result) if isinstance(result, list) else 0
            except Exception:
                return 0

        pppoe, hotspot = await asyncio.gather(
            safe_count(mt.list_pppoe_active()),
            safe_count(mt.list_hotspot_active()),
        )
        return pppoe, hotspot
    except Exception:
        # Fallback: gunakan nilai dari DB (hasil polling terakhir)
        return (
            device.get("pppoe_active", 0),
            device.get("hotspot_active", 0),
        )


@router.get("/status")
async def wallboard_status(user=Depends(get_current_user)):
    """
    Return devices with full real-time metrics for wall display grid.
    - administrator / viewer: melihat SEMUA device
    - user: hanya melihat device yang di-tag di allowed_devices
    """
    db = get_db()
    # Fetch tanpa credentials untuk response (aman dikirim ke client)
    devices_all = await db.devices.find({}, {"_id": 0, "snmp_community": 0, "api_password": 0}).to_list(200)

    # Filter berdasarkan role
    role = user.get("role", "user")
    if role == "user":
        allowed = set(user.get("allowed_devices") or [])
        devices = [d for d in devices_all if d["id"] in allowed]
    else:
        devices = devices_all

    enriched = []

    # ── Fetch PPPoE & Hotspot counts untuk semua device secara paralel ──────────
    # PENTING: butuh api_password untuk autentikasi ke MikroTik → fetch terpisah
    # dari DB, hanya untuk kebutuhan internal session counting (tidak dikirim ke client).
    device_ids = [d["id"] for d in devices]
    devices_with_creds = await db.devices.find(
        {"id": {"$in": device_ids}},
        {"_id": 0}   # ambil SEMUA field termasuk api_password
    ).to_list(200)
    # Index by device id untuk lookup cepat
    creds_map = {d["id"]: d for d in devices_with_creds}

    # Fetch session counts paralel menggunakan device dengan credentials
    session_counts = await asyncio.gather(
        *[_fetch_session_counts(creds_map.get(d["id"], d)) for d in devices],
        return_exceptions=True,
    )
    # Buat dict {device_id: (pppoe_count, hotspot_count)}
    device_sessions: dict = {}
    for d, counts in zip(devices, session_counts):
        if isinstance(counts, tuple) and len(counts) == 2:
            device_sessions[d["id"]] = counts
        else:
            device_sessions[d["id"]] = (
                d.get("pppoe_active", 0),
                d.get("hotspot_active", 0),
            )

    for d in devices:
        # Get latest traffic snapshot for bandwidth
        snap = await db.traffic_snapshots.find_one({"device_id": d["id"]})

        # Get last bandwidth from traffic_history
        # FIXBUG: tambahkan isp_bandwidth ke projection agar PRIORITAS 1 bisa terpakai
        last_bw = await db.traffic_history.find_one(
            {"device_id": d["id"]},
            {"_id": 0, "bandwidth": 1, "isp_bandwidth": 1, "ping_ms": 1, "timestamp": 1},
            sort=[("timestamp", -1)]
        )

        download_bps = 0
        upload_bps = 0
        isp_interfaces = d.get("isp_interfaces", [])

        # ── Konstanta filter virtual interface ───────────────────────────────────
        VIRTUAL_PREFIXES = (
            "bridge", "vlan", "lo", "loopback", "ovpn", "pppoe-", "pptp",
            "l2tp", "eoip", "gre", "wireguard", "wg", "veth", "docker",
            "ip6tnl", "sit", "tun", "tap", "dummy",
        )

        def is_physical(name: str) -> bool:
            """Return True jika interface bukan virtual."""
            n = name.lower()
            return not any(n.startswith(p) for p in VIRTUAL_PREFIXES)

        if last_bw:
            bw = last_bw.get("bandwidth") or {}

            # ── PRIORITAS 1: isp_bandwidth (field baru, paling akurat) ────────
            # Diisi oleh polling.py berdasarkan comment "ISP1..20/WAN/INPUT" di MikroTik
            isp_bw_stored = last_bw.get("isp_bandwidth") or {}
            if isp_bw_stored:
                for iface_bw in isp_bw_stored.values():
                    if isinstance(iface_bw, dict):
                        download_bps += iface_bw.get("download_bps", 0)
                        upload_bps   += iface_bw.get("upload_bps",   0)

            # ── PRIORITAS 2: Fallback — filter bw dengan isp_interfaces ──────
            elif bw and isp_interfaces:
                for iface in isp_interfaces:
                    iface_bw = bw.get(iface, {})
                    if isinstance(iface_bw, dict):
                        download_bps += iface_bw.get("download_bps", 0)
                        upload_bps   += iface_bw.get("upload_bps",   0)

            # ── PRIORITAS 3: Fallback — sum semua interface fisik saja ────────
            # (Digunakan jika MikroTik belum diberi comment ISP/WAN/INPUT)
            elif bw:
                for iface_name, iface_bw in bw.items():
                    if isinstance(iface_bw, dict) and is_physical(iface_name):
                        download_bps += iface_bw.get("download_bps", 0)
                        upload_bps   += iface_bw.get("upload_bps",   0)


        # Determine alert level
        alert_level = "normal"
        cpu = d.get("cpu_load", 0)
        mem = d.get("memory_usage", 0)
        ping = last_bw.get("ping_ms", 0) if last_bw else 0

        if d.get("status") == "offline":
            alert_level = "critical"
        elif cpu > 90 or mem > 90:
            alert_level = "critical"
        elif cpu > 75 or mem > 75 or ping > 100:
            alert_level = "warning"

        pppoe_count, hotspot_count = device_sessions.get(d.get("id"), (0, 0))
        enriched.append({
            "id": d.get("id"),
            "name": d.get("name", ""),
            "identity": d.get("identity", d.get("sys_name", d.get("name", ""))),
            "ip_address": d.get("ip_address", ""),
            "status": d.get("status", "unknown"),
            "model": d.get("model", ""),
            "ros_version": d.get("ros_version", ""),
            "uptime": d.get("uptime", ""),
            "cpu_load": cpu,
            "memory_usage": mem,
            "cpu_temp": d.get("cpu_temp", 0),
            "board_temp": d.get("board_temp", 0),
            "ping_ms": round(ping, 1),
            "download_mbps": round(download_bps / 1_000_000, 2),
            "upload_mbps": round(upload_bps / 1_000_000, 2),
            "last_poll": d.get("last_poll", ""),
            "alert_level": alert_level,
            "isp_interfaces": d.get("isp_interfaces", []),
            # Session counters — live fetch langsung dari MikroTik (sama seperti PPPoE user page)
            "pppoe_active":   pppoe_count,
            "hotspot_active": hotspot_count,
        })


    # Sort: critical first, then warning, then normal; within each group: alphabetical
    order = {"critical": 0, "warning": 1, "normal": 2}
    enriched.sort(key=lambda x: (order.get(x["alert_level"], 3), x["name"]))

    # Summary stats
    total = len(enriched)
    online = sum(1 for d in enriched if d["status"] == "online")
    offline = sum(1 for d in enriched if d["status"] == "offline")
    warning = sum(1 for d in enriched if d["alert_level"] == "warning")
    # Akumulasi session counters dari semua device online
    total_pppoe   = sum(d["pppoe_active"]   for d in enriched if d["status"] == "online")
    total_hotspot = sum(d["hotspot_active"] for d in enriched if d["status"] == "online")

    return {
        "devices": enriched,
        "summary": {
            "total": total,
            "online": online,
            "offline": offline,
            "warning": warning,
            "total_pppoe":   total_pppoe,
            "total_hotspot": total_hotspot,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }


@router.get("/events")
async def wallboard_events(limit: int = 30, user=Depends(get_current_user)):
    """
    Return recent NOC events for the bottom ticker.
    Sources: sla_events (online/offline transitions) + recent alerts.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=24)).isoformat()

    # Get recent SLA events (online/offline transitions)
    sla_events = await db.sla_events.find(
        {"timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(limit)

    # Get recent incidents
    incidents = await db.incidents.find(
        {"created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "title": 1, "severity": 1, "device_name": 1, "created_at": 1, "status": 1}
    ).sort("created_at", -1).to_list(10)

    events = []

    for e in sla_events:
        event_type = e.get("event_type", "")
        color = "green" if event_type == "online" else "red"
        events.append({
            "id": str(e.get("_id", "")),
            "type": event_type,
            "device_name": e.get("device_name", ""),
            "device_id": e.get("device_id", ""),
            "message": f"{e.get('device_name', 'Device')} went {event_type.upper()}",
            "timestamp": e.get("timestamp", ""),
            "color": color,
        })

    for inc in incidents:
        sev = inc.get("severity", "medium")
        color_map = {"critical": "red", "high": "orange", "medium": "yellow", "low": "blue"}
        events.append({
            "id": inc.get("id", ""),
            "type": "incident",
            "device_name": inc.get("device_name", ""),
            "message": f"INC: {inc.get('title', 'Incident')} [{sev.upper()}]",
            "timestamp": inc.get("created_at", ""),
            "color": color_map.get(sev, "yellow"),
        })

    # Sort by timestamp descending
    events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return {"events": events[:limit]}
