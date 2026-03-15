"""
Polling Engine — Hybrid Monitoring (API + SNMP).
================================================
Arsitektur:
  - Data SISTEM  (CPU, RAM, Uptime, Health, PPPoE, Hotspot) via MikroTik REST/API
  - Data TRAFFIC (bandwidth iface) via SNMP v2c 64-bit counters
    └─ Fallback ke API traffic jika SNMP tidak tersedia

Optimasi untuk 100+ device:
  - asyncio.Semaphore(50): maks paralel polling
  - SNMP delta 1-detik + SMA window=3 untuk grafik halus
  - Discovery auto-detect mode (REST/API) — hasil di-cache di DB
  - Offline skip: device gagal ≥6x → poll 1x per 5 siklus
"""
import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta

from core.db import get_db
from mikrotik_api import get_host_only, get_api_client, discover_device
import ping_service

logger = logging.getLogger(__name__)

# ── Konstanta Polling ──────────────────────────────────────────────────────────
POLL_INTERVAL        = 30    # Detik antar siklus polling
DEVICE_TIMEOUT       = 90    # Maks waktu per device (sudah include SNMP 1+s delta)
OFFLINE_GRACE_POLLS  = 2     # Kegagalan beruntun sebelum tandai offline
MAX_CONCURRENT_POLLS = 50    # Semaphore — aman untuk 100+ device
OFFLINE_SKIP_AFTER   = 6     # Jika offline ≥ N kali: mulai skip siklus
OFFLINE_SKIP_CYCLES  = 4     # Skip N siklus sebelum poll ulang

# Keyword ISP — berikan prioritas pada interface ini untuk BW monitoring
_ISP_KEYWORDS = (
    "isp", *[f"isp{i}" for i in range(1, 21)],
    "wan", *[f"wan{i}" for i in range(1, 21)],
    "input", *[f"input{i}" for i in range(1, 21)],
    "uplink", "upstream", "internet", "gateway",
)

# Interface virtual yang tidak perlu di-monitor
_VIRTUAL_IFACE_TYPES = {
    "bridge", "vlan", "pppoe-out", "pppoe-in", "l2tp", "pptp", "ovpn-client",
    "ovpn-server", "sstp-client", "sstp-server", "gre", "eoip", "eoipv6",
    "veth", "wireguard", "loopback", "6to4", "ipip", "ipip6",
}
_VIRTUAL_IFACE_PREFIXES = ("lo", "docker", "veth", "tun", "tap")

# Interface SFP yang kadang di-report running=false di ROS 7.16.2+
_SFP_IFACE_TYPES = {
    "sfp-sfpplus", "sfpplus", "sfp", "10g-sfp", "10gbase-x",
    "qsfp", "qsfp+", "qsfp28", "combo", "sfp-sfpplus-combo",
    "10gsfp-sfpplus", "sfp28", "25g-sfp28", "40g-qsfp", "100g-qsfp28",
}
_SFP_IFACE_PREFIXES = ("sfp", "sfpplus", "qsfp", "combo")


# ── Module: Auto-Discovery ─────────────────────────────────────────────────────

async def _ensure_api_mode(device: dict, db) -> dict:
    """
    Pastikan device memiliki api_mode yang valid.
    Jika belum ada atau 'unknown', jalankan discover_device() dan simpan ke DB.
    Return device dict yang sudah ter-update.
    """
    current_mode = device.get("api_mode", "")
    if current_mode in ("rest", "api"):
        return device  # sudah diketahui, tidak perlu discover ulang

    logger.info(f"Auto-discover mode untuk {device.get('name', '?')} [{device.get('ip_address', '?')}]...")
    disc = await discover_device(device)

    if disc["success"]:
        update_fields = {
            "api_mode":      disc["api_mode"],
            "ros_version":   disc.get("ros_version", ""),
            "model":         disc.get("board_name", "") or device.get("model", ""),
        }
        if disc["api_mode"] == "rest":
            update_fields["use_https"] = disc.get("use_https", False)
            if disc.get("rest_port"):
                update_fields["api_port"] = disc["rest_port"]
        elif disc.get("api_port"):
            update_fields["api_port"] = disc["api_port"]

        await db.devices.update_one({"id": device["id"]}, {"$set": update_fields})
        device = {**device, **update_fields}
        logger.info(f"Discovery OK: {device.get('name','?')} → mode={disc['api_mode']} ROS={disc.get('ros_version','?')}")
    else:
        logger.warning(f"Discovery GAGAL: {device.get('name','?')} — pertahankan mode default 'rest'")
        device = {**device, "api_mode": "rest"}

    return device


# ── Module: SNMP Traffic ───────────────────────────────────────────────────────

async def _get_traffic_snmp(
    device: dict,
    running_ifaces: list,
    isp_detected: list,
    device_id: str,
) -> dict:
    """
    Ambil bandwidth traffic via SNMP v2c (metode utama Hybrid Monitoring).

    Fitur:
      - 64-bit HC counters (ifHCInOctets / ifHCOutOctets) — akurat > 4Gbps
      - Delta 1-detik: T1 → sleep 1s → T2 → bps = (T2-T1)*8
      - SMA window=3 untuk grafik halus
      - Fallback ke {} jika SNMP tidak tersedia

    Return: {iface_name: {download_bps, upload_bps, status, source}}
    """
    try:
        from snmp_poller import get_snmp_traffic
    except ImportError:
        logger.debug("snmp_poller tidak tersedia — fallback ke API traffic")
        return {}

    host      = get_host_only(device.get("ip_address", ""))
    community = device.get("snmp_community", "public") or "public"

    if not host:
        return {}

    # Tentukan interface yang akan di-monitor via SNMP
    # ISP interface selalu masuk, sisanya sampai 64 interface
    isp_set  = set(isp_detected)
    isp_if   = [n for n in running_ifaces if n in isp_set]
    rest_if  = [n for n in running_ifaces if n not in isp_set]
    max_rest = max(0, 64 - len(isp_if))
    iface_filter = isp_if + rest_if[:max_rest]

    try:
        bw = await asyncio.wait_for(
            get_snmp_traffic(
                host=host,
                community=community,
                device_id=device_id,
                iface_filter=iface_filter if iface_filter else None,
                snmp_timeout=5,
                apply_smoothing=True,
            ),
            timeout=15  # total max: T1 walk + 1s sleep + T2 walk
        )

        if bw:
            logger.info(
                f"SNMP traffic OK [{device.get('name','?')}]: "
                f"{len(bw)} ifaces community={community}"
            )
        else:
            logger.debug(f"SNMP traffic kosong [{device.get('name','?')}] — fallback ke API")

        return bw

    except asyncio.TimeoutError:
        logger.debug(f"SNMP timeout [{device.get('name','?')}] — fallback ke API")
        return {}
    except Exception as e:
        logger.debug(f"SNMP traffic error [{device.get('name','?')}]: {e}")
        return {}


# ── Module: API Traffic Fallback ───────────────────────────────────────────────

async def _get_traffic_api_rest(mt, running_ifaces: list, isp_detected: list, device_name: str) -> dict:
    """Ambil bandwidth via monitor-traffic REST API (ROS 7.x). Fallback jika SNMP gagal."""
    bw_precomputed = {}
    if not running_ifaces:
        return bw_precomputed

    isp_set  = set(isp_detected)
    sfp_set  = {n for n in running_ifaces if n.lower().startswith(_SFP_IFACE_PREFIXES)}
    isp_if   = [n for n in running_ifaces if n in isp_set]
    sfp_if   = [n for n in running_ifaces if n in sfp_set and n not in isp_set]
    rest_if  = [n for n in running_ifaces if n not in isp_set and n not in sfp_set]
    max_rest = max(0, 64 - len(isp_if) - len(sfp_if))
    priority = isp_if + sfp_if + rest_if[:max_rest]

    async def _one(iface_name):
        try:
            r = await mt._async_req(
                "POST", "interface/monitor-traffic",
                {"interface": iface_name, "once": True},
                timeout=10
            )
            if isinstance(r, list) and r:
                r = r[0]
            if isinstance(r, dict):
                return (iface_name, {
                    "download_bps": int(r.get("rx-bits-per-second", 0) or 0),
                    "upload_bps":   int(r.get("tx-bits-per-second", 0) or 0),
                    "status":       "up",
                    "source":       "api_rest",
                })
        except Exception:
            pass
        return None

    results = await asyncio.gather(*[_one(n) for n in priority], return_exceptions=True)
    for r in results:
        if r and not isinstance(r, Exception):
            bw_precomputed[r[0]] = r[1]
    return bw_precomputed


async def _get_traffic_api_protocol(mt, device, running_ifaces: list) -> tuple:
    """Ambil raw byte stats via API Protocol (ROS 6.x). Fallback jika SNMP gagal."""
    try:
        stats_result = await mt.get_all_interface_stats()
        cur_stats    = stats_result.get("stats", {})
        isp_from_api = stats_result.get("isp_interfaces", [])
        isp_comments = stats_result.get("isp_comments", {})
        return cur_stats, isp_from_api, isp_comments
    except Exception as e:
        logger.warning(f"ROS6 stats gagal [{device.get('name','?')}]: {e}")
        return {}, [], {}


# ── Core: Hybrid Poll ─────────────────────────────────────────────────────────

async def poll_via_api(device: dict) -> dict:
    """
    Hybrid poll: API untuk data sistem, SNMP untuk traffic bandwidth.
    Fallback ke API traffic jika SNMP tidak tersedia.
    """
    EMPTY_RESULT = {
        "reachable":      False,
        "poll_mode":      "api_failed",
        "ping":           {"reachable": False, "avg": 0, "jitter": 0, "loss": 100},
        "system":         {},
        "cpu":            0,
        "memory":         {"total": 0, "used": 0, "percent": 0},
        "interfaces":     [],
        "traffic":        {},
        "health":         {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0},
        "bw_precomputed": {},
        "pppoe_active":   0,
        "hotspot_active": 0,
    }

    try:
        mt       = get_api_client(device)
        api_mode = device.get("api_mode", "rest")
        dev_name = device.get("name", device.get("ip_address", "?"))
        dev_id   = device.get("id", "")

        # ══════════════════════════════════════════════════════════════════════
        # FASE 1: Data Sistem via API (paralel)
        # ══════════════════════════════════════════════════════════════════════
        async def _empty(): return {}

        sys_res, identity_res, health_raw, ifaces_raw = await asyncio.gather(
            mt.get_system_resource(),
            mt._async_req("GET", "system/identity") if hasattr(mt, "_async_req") else _empty(),
            mt.get_system_health(),
            mt.list_interfaces(),
            return_exceptions=True,
        )

        if isinstance(sys_res,      Exception): sys_res      = {}
        if isinstance(identity_res, Exception): identity_res = {}
        if isinstance(health_raw,   Exception): health_raw   = {}
        if isinstance(ifaces_raw,   Exception): ifaces_raw   = []

        if not sys_res and not identity_res:
            logger.warning(f"API tidak merespon untuk {dev_name}")
            return EMPTY_RESULT

        # ── Identity ─────────────────────────────────────────────────────────
        router_name = ""
        if isinstance(identity_res, dict):
            router_name = identity_res.get("name", "")
        if not router_name:
            router_name = device.get("name", device.get("ip_address", ""))

        # ── Sistem Info ───────────────────────────────────────────────────────
        sys_info          = {}
        uptime_formatted  = "N/A"
        uptime_seconds    = 0

        if sys_res:
            board_name   = sys_res.get("board-name", "")
            ros_version  = sys_res.get("version", "")
            architecture = sys_res.get("architecture-name", "")

            uptime_raw = str(sys_res.get("uptime", "") or "")
            try:
                d = int(re.search(r"(\d+)d", uptime_raw).group(1)) if "d" in uptime_raw else 0
                h = int(re.search(r"(\d+)h", uptime_raw).group(1)) if "h" in uptime_raw else 0
                m = int(re.search(r"(\d+)m", uptime_raw).group(1)) if "m" in uptime_raw else 0
                s_m = re.search(r"(\d+)s", uptime_raw)
                sec = int(s_m.group(1)) if s_m else 0
                uptime_seconds   = d * 86400 + h * 3600 + m * 60 + sec
                uptime_formatted = f"{d}d {h}h {m}m"
            except Exception:
                uptime_formatted = uptime_raw or "N/A"

            sys_info = {
                "sys_name":         router_name,
                "board_name":       board_name,
                "identity":         router_name,
                "ros_version":      ros_version,
                "architecture":     architecture,
                "uptime_formatted": uptime_formatted,
                "uptime_seconds":   uptime_seconds,
                "serial":           "",
                "firmware":         ros_version,
            }

        # ── CPU ───────────────────────────────────────────────────────────────
        cpu_load = 0
        try:
            cpu_load = int(str(sys_res.get("cpu-load", "0") or "0").rstrip("%"))
        except (ValueError, TypeError):
            pass

        # ── Memory ────────────────────────────────────────────────────────────
        memory = {"total": 0, "used": 0, "percent": 0}
        try:
            total_mem = int(sys_res.get("total-memory", 0) or 0)
            free_mem  = int(sys_res.get("free-memory",  0) or 0)
            used_mem  = max(0, total_mem - free_mem)
            if total_mem > 0:
                memory = {
                    "total":   total_mem,
                    "used":    used_mem,
                    "percent": round((used_mem / total_mem) * 100),
                }
        except (ValueError, TypeError):
            pass

        # ── Health ────────────────────────────────────────────────────────────
        health = {
            "cpu_temp":   health_raw.get("cpu_temp",   0) if isinstance(health_raw, dict) else 0,
            "board_temp": health_raw.get("board_temp", 0) if isinstance(health_raw, dict) else 0,
            "voltage":    health_raw.get("voltage",    0) if isinstance(health_raw, dict) else 0,
            "power":      health_raw.get("power",      0) if isinstance(health_raw, dict) else 0,
        }

        # ── Interface List + ISP Detection ────────────────────────────────────
        isp_detected   = []
        interfaces     = []
        running_ifaces = []

        for iface in (ifaces_raw if isinstance(ifaces_raw, list) else []):
            name     = iface.get("name", "")
            itype    = iface.get("type", "").lower()
            running  = iface.get("running", False)
            disabled = str(iface.get("disabled", "false")).lower() == "true"
            comment  = str(iface.get("comment", "") or "").lower()

            is_sfp = itype in _SFP_IFACE_TYPES or name.lower().startswith(_SFP_IFACE_PREFIXES)
            if is_sfp and not disabled:
                running = True  # SFP bonded ke switch chip: override running=false

            status = "down" if disabled else ("up" if running else "down")

            is_virtual = (
                itype in _VIRTUAL_IFACE_TYPES
                or name.lower().startswith(_VIRTUAL_IFACE_PREFIXES)
                or name.startswith("<")
            )

            # ISP detection via comment
            if name and any(kw in comment for kw in _ISP_KEYWORDS):
                isp_detected.append(name)

            if name:
                interfaces.append({
                    "index":   iface.get(".id", ""),
                    "name":    name,
                    "type":    itype,
                    "status":  status,
                    "speed":   0,
                    "virtual": is_virtual,
                    "is_sfp":  is_sfp,
                })

            if running and not disabled and name and not is_virtual:
                running_ifaces.append(name)

        # ══════════════════════════════════════════════════════════════════════
        # FASE 2: PPPoE & Hotspot Count via API (paralel, ROS7 REST only)
        # ══════════════════════════════════════════════════════════════════════
        pppoe_active   = 0
        hotspot_active = 0

        if api_mode == "api":
            # ROS6: fetch via thread
            try:
                pppoe_list_r6 = await asyncio.to_thread(mt._list_resource, "/ppp/active")
                pppoe_active  = len(pppoe_list_r6) if isinstance(pppoe_list_r6, list) else 0
            except Exception:
                pass
            try:
                hs_list_r6    = await asyncio.to_thread(mt._list_resource, "/ip/hotspot/active")
                hotspot_active = len(hs_list_r6) if isinstance(hs_list_r6, list) else 0
            except Exception:
                pass
        else:
            # ROS7: REST API
            try:
                pppoe_list, hotspot_list = await asyncio.gather(
                    mt.list_pppoe_active(),
                    mt.list_hotspot_active(),
                    return_exceptions=True,
                )
                pppoe_active   = len(pppoe_list)   if isinstance(pppoe_list,   list) else 0
                hotspot_active = len(hotspot_list) if isinstance(hotspot_list, list) else 0
            except Exception:
                pass

        logger.debug(
            f"Sessions [{dev_name}]: pppoe={pppoe_active} hotspot={hotspot_active}"
        )

        # ══════════════════════════════════════════════════════════════════════
        # FASE 3: Traffic via SNMP (utama) → fallback ke API
        # ══════════════════════════════════════════════════════════════════════
        bw_precomputed   = {}
        iface_stats_raw  = {}
        isp_from_api     = isp_detected[:]
        isp_comments     = {}
        poll_source      = "snmp"

        if running_ifaces:
            # ── Coba SNMP terlebih dahulu ─────────────────────────────────────
            bw_precomputed = await _get_traffic_snmp(
                device, running_ifaces, isp_detected, dev_id
            )

            # ── Fallback ke API jika SNMP kosong ─────────────────────────────
            if not bw_precomputed:
                poll_source = "api_fallback"
                if api_mode == "rest" and hasattr(mt, "_async_req"):
                    bw_precomputed = await _get_traffic_api_rest(
                        mt, running_ifaces, isp_detected, dev_name
                    )
                    logger.info(
                        f"SNMP fallback → REST monitor-traffic [{dev_name}]: "
                        f"{len(bw_precomputed)} ifaces"
                    )
                elif api_mode == "api":
                    iface_stats_raw, isp_from_api, isp_comments = \
                        await _get_traffic_api_protocol(mt, device, running_ifaces)
                    if iface_stats_raw:
                        poll_source = "api_delta_ros6"
                        logger.info(f"SNMP fallback → ROS6 delta [{dev_name}]: {len(iface_stats_raw)} ifaces")

        mode_label = f"{api_mode}_hybrid_snmp" if poll_source == "snmp" else f"{api_mode}_{poll_source}"
        logger.info(
            f"Poll OK [{mode_label}] {dev_name}: "
            f"cpu={cpu_load}% mem={memory['percent']}% "
            f"ifaces={len(running_ifaces)} bw={len(bw_precomputed)} "
            f"isp={isp_from_api} source={poll_source}"
        )

        # ── ROS6: return langsung dengan iface_stats_raw ──────────────────────
        if api_mode == "api" and not bw_precomputed and iface_stats_raw:
            return {
                "reachable":       True,
                "poll_mode":       "api_protocol_hybrid",
                "poll_source":     poll_source,
                "ping":            {"reachable": True, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 0},
                "system":          sys_info,
                "cpu":             cpu_load,
                "memory":          memory,
                "interfaces":      interfaces,
                "traffic":         {},
                "health":          health,
                "bw_precomputed":  {},
                "iface_stats_raw": iface_stats_raw,
                "running_ifaces":  running_ifaces,
                "isp_detected":    isp_from_api,
                "isp_comments":    isp_comments,
                "pppoe_active":    pppoe_active,
                "hotspot_active":  hotspot_active,
            }

        return {
            "reachable":       True,
            "poll_mode":       mode_label,
            "poll_source":     poll_source,
            "ping":            {"reachable": True, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 0},
            "system":          sys_info,
            "cpu":             cpu_load,
            "memory":          memory,
            "interfaces":      interfaces,
            "traffic":         {},
            "health":          health,
            "bw_precomputed":  bw_precomputed,
            "iface_stats_raw": {},
            "running_ifaces":  running_ifaces,
            "isp_detected":    isp_from_api,
            "pppoe_active":    pppoe_active,
            "hotspot_active":  hotspot_active,
        }

    except Exception as e:
        logger.warning(f"API poll gagal untuk {device.get('name', '?')}: {e}")
        return {
            "reachable":      False,
            "poll_mode":      "api_failed",
            "ping":           {"reachable": False, "avg": 0, "jitter": 0, "loss": 100},
            "system":         {},
            "cpu":            0,
            "memory":         {"total": 0, "used": 0, "percent": 0},
            "interfaces":     [],
            "traffic":        {},
            "health":         {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0},
            "bw_precomputed": {},
        }


# ── poll_single_device ────────────────────────────────────────────────────────

async def poll_single_device(device: dict) -> dict:
    """
    Poll satu device: auto-discover mode → Hybrid poll → simpan ke DB.
    """
    db  = get_db()
    did = device["id"]

    # ── Auto-discover mode jika belum ada ────────────────────────────────────
    device = await _ensure_api_mode(device, db)

    # ── Hybrid Poll ───────────────────────────────────────────────────────────
    result = await poll_via_api(device)

    # ── Offline grace period ──────────────────────────────────────────────────
    consecutive_failures = device.get("consecutive_poll_failures", 0)
    old_status = device.get("status", "unknown")

    if result["reachable"]:
        new_status = "online"
        consecutive_failures = 0
        # Jika sebelumnya offline, clear SMA cache agar tidak ada data stale
        if old_status == "offline":
            try:
                from snmp_poller import clear_sma_cache
                clear_sma_cache(did)
            except Exception:
                pass
    else:
        consecutive_failures += 1
        if consecutive_failures >= OFFLINE_GRACE_POLLS:
            new_status = "offline"
        else:
            new_status = old_status if old_status in ("online", "offline") else "offline"
            logger.info(
                f"Poll gagal {device.get('name', did)} "
                f"({consecutive_failures}/{OFFLINE_GRACE_POLLS}), grace period aktif"
            )

    now = datetime.now(timezone.utc).isoformat()

    update = {
        "status":                    new_status,
        "last_poll":                 now,
        "last_poll_data":            result,
        "consecutive_poll_failures": consecutive_failures,
    }

    if result["reachable"] and result.get("system"):
        s      = result["system"]
        health = result.get("health", {})
        update.update({
            "model":          s.get("board_name", ""),
            "sys_name":       s.get("sys_name", ""),
            "identity":       s.get("identity", s.get("sys_name", "")),
            "architecture":   s.get("architecture", ""),
            "ros_version":    s.get("ros_version", ""),
            "uptime":         s.get("uptime_formatted", ""),
            "serial":         s.get("serial", ""),
            "cpu_load":       result.get("cpu", 0),
            "memory_usage":   result.get("memory", {}).get("percent", 0),
            "cpu_temp":       health.get("cpu_temp",   0),
            "board_temp":     health.get("board_temp", 0),
            "voltage":        health.get("voltage",    0),
            "power":          health.get("power",      0),
            "pppoe_active":   result.get("pppoe_active",   0),
            "hotspot_active": result.get("hotspot_active", 0),
        })

    # ── SLA Event ─────────────────────────────────────────────────────────────
    if old_status != new_status and new_status in ("online", "offline"):
        try:
            await db.sla_events.insert_one({
                "device_id":   did,
                "device_name": device.get("name", did),
                "event_type":  new_status,
                "from_status": old_status,
                "timestamp":   now,
            })
            logger.info(f"SLA event: {device.get('name', did)} → {new_status}")
        except Exception as sla_err:
            logger.debug(f"SLA event write gagal: {sla_err}")

    await db.devices.update_one({"id": did}, {"$set": update})

    # ── ISP Interface update ───────────────────────────────────────────────────
    isp_detected_in_poll = result.get("isp_detected", [])
    if isp_detected_in_poll:
        current_isp = device.get("isp_interfaces", [])
        if set(isp_detected_in_poll) != set(current_isp):
            await db.devices.update_one(
                {"id": did},
                {"$set": {"isp_interfaces": isp_detected_in_poll}}
            )

    isp_interfaces_for_bw = isp_detected_in_poll or device.get("isp_interfaces", [])

    # ── Notifikasi WhatsApp ───────────────────────────────────────────────────
    try:
        from services.notification_service import check_and_notify
        await check_and_notify(device, result, update)
    except Exception as e:
        logger.debug(f"Notification skip: {e}")

    # ── Bandwidth kalkulasi ────────────────────────────────────────────────────
    ping_data = result.get("ping", {})
    bw        = result.get("bw_precomputed", {})

    # ROS6 fallback: hitung delta bps dari raw bytes
    iface_stats_raw = result.get("iface_stats_raw", {})
    if iface_stats_raw and not bw:
        try:
            now_ts     = datetime.now(timezone.utc).timestamp()
            running_set = set(result.get("running_ifaces", []))

            snap_doc   = await db.traffic_snapshots.find_one({"device_id": did}, {"_id": 0})
            prev_stats = snap_doc.get("iface_bytes", {}) if snap_doc else {}
            prev_ts    = snap_doc.get("ts")              if snap_doc else None

            if prev_stats and prev_ts:
                elapsed = max(now_ts - prev_ts, 1)
                for iface_name, cur in iface_stats_raw.items():
                    if iface_name not in running_set:
                        continue
                    prev = prev_stats.get(iface_name)
                    if not prev:
                        continue
                    rx_delta = max(0, cur.get("rx-bytes", 0) - prev.get("rx-bytes", 0))
                    tx_delta = max(0, cur.get("tx-bytes", 0) - prev.get("tx-bytes", 0))
                    dl_bps   = int((rx_delta * 8) / elapsed)
                    ul_bps   = int((tx_delta * 8) / elapsed)

                    # Terapkan SMA untuk ROS6 delta juga
                    try:
                        from snmp_poller import apply_sma
                        dl_bps, ul_bps = apply_sma(did, iface_name, dl_bps, ul_bps)
                    except Exception:
                        pass

                    bw[iface_name] = {
                        "download_bps": dl_bps,
                        "upload_bps":   ul_bps,
                        "status":       "up",
                        "source":       "api_delta_ros6",
                    }
                logger.info(
                    f"ROS6 delta bw OK: {device.get('name','?')} "
                    f"elapsed={elapsed:.1f}s bw={len(bw)} ifaces"
                )
        except Exception as e:
            logger.warning(f"ROS6 delta calc gagal untuk {device.get('name','?')}: {e}")

    # ── ISP bandwidth ──────────────────────────────────────────────────────────
    isp_bw = {}
    if bw and isp_interfaces_for_bw:
        for iface_name in isp_interfaces_for_bw:
            iface_data = bw.get(iface_name)
            if isinstance(iface_data, dict):
                isp_bw[iface_name] = {
                    "download_bps": iface_data.get("download_bps", 0),
                    "upload_bps":   iface_data.get("upload_bps",   0),
                    "status":       iface_data.get("status", "up"),
                }

    # Total
    isp_dl_bps = sum(v.get("download_bps", 0) for v in isp_bw.values())
    isp_ul_bps = sum(v.get("upload_bps",   0) for v in isp_bw.values())
    total_dl   = sum(v.get("download_bps", 0) for v in bw.values() if isinstance(v, dict))
    total_ul   = sum(v.get("upload_bps",   0) for v in bw.values() if isinstance(v, dict))

    eff_dl = isp_dl_bps if isp_bw else total_dl
    eff_ul = isp_ul_bps if isp_bw else total_ul
    logger.info(
        f"BW [{device.get('name','?')}] source={result.get('poll_source','?')}: "
        f"isp={list(isp_bw.keys())} "
        f"dl={eff_dl/1_000_000:.2f}Mbps ul={eff_ul/1_000_000:.2f}Mbps"
    )

    # ── ICMP Ping ─────────────────────────────────────────────────────────────
    real_ping_ms = ping_data.get("avg", 0) or 0
    if not real_ping_ms and result.get("reachable"):
        try:
            ip_only = get_host_only(device.get("ip_address", ""))
            if ip_only:
                pr = await ping_service.ping_host(ip_only, count=2, timeout=2)
                real_ping_ms = pr.get("avg", 0) or 0
        except Exception:
            real_ping_ms = 0

    # ── Simpan ke traffic_history ──────────────────────────────────────────────
    snapshot = {
        "device_id":      did,
        "timestamp":      now,
        "bandwidth":      bw,
        "isp_bandwidth":  isp_bw,
        "download_mbps":  round((isp_dl_bps if isp_bw else total_dl) / 1_000_000, 3),
        "upload_mbps":    round((isp_ul_bps if isp_bw else total_ul) / 1_000_000, 3),
        "cpu":            result.get("cpu", 0),
        "memory_percent": result.get("memory", {}).get("percent", 0),
        "ping_ms":        round(real_ping_ms, 1),
        "jitter_ms":      ping_data.get("jitter", 0) or 0,
        "poll_source":    result.get("poll_source", "unknown"),
    }
    try:
        await db.traffic_history.insert_one(snapshot)
        count = await db.traffic_history.count_documents({"device_id": did})
        if count > 2880:
            oldest = await db.traffic_history.find(
                {"device_id": did}, {"_id": 1}
            ).sort("timestamp", 1).limit(count - 2880).to_list(count - 2880)
            ids = [d["_id"] for d in oldest]
            if ids:
                await db.traffic_history.delete_many({"_id": {"$in": ids}})
    except Exception as hist_err:
        logger.debug(f"Traffic history write gagal: {hist_err}")

    # ── InfluxDB (opsional) ───────────────────────────────────────────────────
    if bw:
        try:
            from services.metrics_service import write_device_metrics, is_enabled
            if is_enabled():
                await asyncio.to_thread(
                    write_device_metrics, did, device.get("name", did),
                    {
                        "cpu":       result.get("cpu", 0),
                        "memory":    result.get("memory", {}),
                        "ping":      ping_data,
                        "health":    result.get("health", {}),
                        "bandwidth": bw,
                    },
                )
        except Exception as e:
            logger.debug(f"InfluxDB write skip: {e}")

    # ── Update traffic_snapshots (untuk delta ROS6 berikutnya) ────────────────
    snap_update = {"device_id": did, "timestamp": now, "traffic": {}}
    if iface_stats_raw:
        snap_update["iface_bytes"] = iface_stats_raw
        snap_update["ts"]          = datetime.now(timezone.utc).timestamp()
    await db.traffic_snapshots.update_one(
        {"device_id": did}, {"$set": snap_update}, upsert=True
    )

    return result


# ── Polling Loop ──────────────────────────────────────────────────────────────

async def polling_loop():
    """
    Background task: poll semua device setiap POLL_INTERVAL detik.
    Semaphore(50) membatasi concurrency agar tidak overload server.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_POLLS)

    async def poll_with_semaphore(dev):
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    poll_single_device(dev),
                    timeout=DEVICE_TIMEOUT
                )
            except asyncio.TimeoutError:
                name = dev.get("name", dev.get("ip_address", "?"))
                logger.warning(f"Poll timeout {DEVICE_TIMEOUT}s untuk {name}, skip siklus ini")
                return None
            except Exception as e:
                logger.error(f"Poll error untuk {dev.get('name', '?')}: {e}")
                return None

    while True:
        start = asyncio.get_running_loop().time()
        try:
            db      = get_db()
            devices = await db.devices.find({}, {"_id": 0}).to_list(None)
            if devices:
                tick = getattr(polling_loop, "_tick", 0) + 1
                polling_loop._tick = tick

                def _should_poll(dev):
                    fails = dev.get("consecutive_poll_failures", 0)
                    if fails < OFFLINE_SKIP_AFTER:
                        return True
                    return (tick % (OFFLINE_SKIP_CYCLES + 1)) == 0

                to_poll = [d for d in devices if _should_poll(d)]
                skipped = len(devices) - len(to_poll)
                if skipped:
                    logger.debug(f"Polling: {len(to_poll)} active, {skipped} offline skipped")

                logger.debug(
                    f"Polling {len(to_poll)} device "
                    f"(max {MAX_CONCURRENT_POLLS} paralel, hybrid SNMP+API)..."
                )
                await asyncio.gather(
                    *[poll_with_semaphore(d) for d in to_poll],
                    return_exceptions=True
                )

            # Bersihkan snapshots lama (> 2 jam)
            snap_cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
            await db.traffic_snapshots.delete_many({"ts": {"$lt": snap_cutoff}})

            # Bersihkan traffic_history lama (> 31 hari)
            cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            await db.traffic_history.delete_many({"timestamp": {"$lt": cutoff}})

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll loop error: {e}")

        elapsed    = asyncio.get_running_loop().time() - start
        sleep_time = max(1, POLL_INTERVAL - elapsed)
        await asyncio.sleep(sleep_time)
