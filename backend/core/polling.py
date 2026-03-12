import asyncio
import logging
from datetime import datetime, timezone, timedelta
from core.db import get_db
import snmp_service
from mikrotik_api import get_host_only, get_api_client

logger = logging.getLogger(__name__)
POLL_INTERVAL = 30
OFFLINE_GRACE_POLLS = 2   # Number of consecutive failed polls before marking offline


# ── REST API Fallback ─────────────────────────────────────────────────────────
async def poll_via_rest_api(device: dict) -> dict:
    """
    Ambil data monitoring via MikroTik REST API sebagai fallback dari SNMP.
    Menghasilkan struktur data yang kompatibel dengan snmp_service.poll_device().
    Fix: identity dari /system/identity, bandwidth dari monitor-traffic.
    """
    EMPTY_RESULT = {
        "reachable": False, "poll_mode": "rest_api_failed",
        "ping": {"reachable": False, "avg": 0, "jitter": 0, "loss": 100},
        "system": {}, "cpu": 0,
        "memory": {"total": 0, "used": 0, "percent": 0},
        "interfaces": [], "traffic": {},
        "health": {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0},
        "bw_precomputed": {},
    }
    try:
        mt = get_api_client(device)

        # ── Ambil semua data secara paralel ──────────────────────────────────
        async def _empty_coro():
            return {}

        sys_res, identity_res, health_raw, ifaces_raw = await asyncio.gather(
            mt.get_system_resource(),
            mt._async_req("GET", "system/identity") if hasattr(mt, "_async_req") else _empty_coro(),
            mt.get_system_health(),
            mt.list_interfaces(),
            return_exceptions=True,
        )


        # Bersihkan exceptions
        if isinstance(sys_res, Exception):      sys_res      = {}
        if isinstance(identity_res, Exception): identity_res = {}
        if isinstance(health_raw, Exception):   health_raw   = {}
        if isinstance(ifaces_raw, Exception):   ifaces_raw   = []

        # Cek apakah REST API bisa dijangkau sama sekali
        if not sys_res and not identity_res:
            logger.warning(f"REST API tidak merespon untuk {device.get('name','?')}")
            return EMPTY_RESULT

        # ── Identity (nama router) ── HARUS dari /system/identity bukan platform ──
        router_name = ""
        if isinstance(identity_res, dict):
            router_name = identity_res.get("name", "")
        # Fallback: gunakan nama device dari DB
        if not router_name:
            router_name = device.get("name", device.get("ip_address", ""))

        # ── Sistem Info ──────────────────────────────────────────────────────
        sys_info = {}
        board_name = ""
        ros_version = ""
        architecture = ""
        uptime_formatted = "N/A"
        uptime_seconds = 0

        if sys_res:
            import re
            board_name   = sys_res.get("board-name", "")
            ros_version  = sys_res.get("version", "")
            architecture = sys_res.get("architecture-name", "")

            # Parse uptime ROS format: "3d15h30m10s"
            uptime_raw = str(sys_res.get("uptime", "") or "")
            try:
                d = int(re.search(r"(\d+)d", uptime_raw).group(1)) if "d" in uptime_raw else 0
                h = int(re.search(r"(\d+)h", uptime_raw).group(1)) if "h" in uptime_raw else 0
                m = int(re.search(r"(\d+)m", uptime_raw).group(1)) if "m" in uptime_raw else 0
                s_match = re.search(r"(\d+)s", uptime_raw)
                sec = int(s_match.group(1)) if s_match else 0
                uptime_seconds = d * 86400 + h * 3600 + m * 60 + sec
                uptime_formatted = f"{d}d {h}h {m}m"
            except Exception:
                uptime_formatted = uptime_raw or "N/A"

            sys_info = {
                "sys_name":         router_name,
                "board_name":       board_name,
                "identity":         router_name,   # ← nama router dari /system/identity
                "ros_version":      ros_version,
                "architecture":     architecture,
                "uptime_formatted": uptime_formatted,
                "uptime_seconds":   uptime_seconds,
                "serial":           "",
                "firmware":         ros_version,
            }

        # ── CPU ──────────────────────────────────────────────────────────────
        cpu_load = 0
        try:
            cpu_load = int(str(sys_res.get("cpu-load", "0") or "0").rstrip("%"))
        except (ValueError, TypeError):
            pass

        # ── Memory ───────────────────────────────────────────────────────────
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

        # ── Health (suhu, voltage) ────────────────────────────────────────────
        health = {
            "cpu_temp":   health_raw.get("cpu_temp",   0) if isinstance(health_raw, dict) else 0,
            "board_temp": health_raw.get("board_temp", 0) if isinstance(health_raw, dict) else 0,
            "voltage":    health_raw.get("voltage",    0) if isinstance(health_raw, dict) else 0,
            "power":      health_raw.get("power",      0) if isinstance(health_raw, dict) else 0,
        }

        # ── Interfaces ───────────────────────────────────────────────────────
        interfaces = []
        running_ifaces = []
        for iface in (ifaces_raw if isinstance(ifaces_raw, list) else []):
            name     = iface.get("name", "")
            running  = iface.get("running", False)
            disabled = str(iface.get("disabled", "false")).lower() == "true"
            status   = "down" if disabled else ("up" if running else "down")
            interfaces.append({"index": iface.get(".id", ""), "name": name, "status": status, "speed": 0})
            if running and not disabled and name:
                running_ifaces.append(name)

        # ── Bandwidth via monitor-traffic (REST API) ──────────────────────────
        # Ambil bandwidth real-time untuk setiap interface yang running
        # ROS /rest/interface/monitor-traffic POST → {rx-bits-per-second, tx-bits-per-second}
        bw_precomputed = {}
        if running_ifaces and hasattr(mt, "_async_req"):
            async def get_iface_traffic(iface_name):
                try:
                    r = await mt._async_req(
                        "POST", "interface/monitor-traffic",
                        {"interface": iface_name, "once": ""}
                    )
                    if isinstance(r, list) and r:
                        r = r[0]
                    if isinstance(r, dict):
                        rx_bps = int(r.get("rx-bits-per-second", 0) or 0)
                        tx_bps = int(r.get("tx-bits-per-second", 0) or 0)
                        return (iface_name, {
                            "download_bps": rx_bps,
                            "upload_bps":   tx_bps,
                            "status":       "up",
                        })
                except Exception:
                    pass
                return None

            # Limit ke 16 interface teratas agar tidak timeout
            tasks = [get_iface_traffic(n) for n in running_ifaces[:16]]
            bw_results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in bw_results:
                if r and not isinstance(r, Exception):
                    bw_precomputed[r[0]] = r[1]

        logger.info(
            f"REST API poll OK: {device.get('name','?')} "
            f"cpu={cpu_load}% mem={memory['percent']}% "
            f"ifaces={len(running_ifaces)} bw={len(bw_precomputed)}"
        )

        return {
            "reachable":      True,
            "poll_mode":      "rest_api",
            "ping":           {"reachable": True, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 0},
            "system":         sys_info,
            "cpu":            cpu_load,
            "memory":         memory,
            "interfaces":     interfaces,
            "traffic":        {},
            "health":         health,
            "bw_precomputed": bw_precomputed,
        }

    except Exception as e:
        logger.warning(f"REST API fallback gagal untuk {device.get('name','?')}: {e}")
        return {
            "reachable": False, "poll_mode": "rest_api_failed",
            "ping": {"reachable": False, "avg": 0, "jitter": 0, "loss": 100},
            "system": {}, "cpu": 0,
            "memory": {"total": 0, "used": 0, "percent": 0},
            "interfaces": [], "traffic": {},
            "health": {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0},
            "bw_precomputed": {},
        }


async def poll_single_device(device: dict) -> dict:
    db = get_db()
    did = device["id"]
    # SNMP butuh plain IP (tanpa port)
    host = get_host_only(device["ip_address"])
    port = device.get("snmp_port", 161)
    comm = device.get("snmp_community", "public")

    # ── Coba SNMP terlebih dahulu ─────────────────────────────────────────────
    snmp_ok = False
    result   = None
    try:
        result = await asyncio.wait_for(snmp_service.poll_device(host, port, comm), timeout=25)
        snmp_ok = result.get("reachable", False)
    except Exception:
        snmp_ok = False

    # ── Fallback ke REST API jika SNMP tidak berhasil ─────────────────────────
    if not snmp_ok:
        api_mode = device.get("api_mode", "rest")
        if api_mode in ("rest", "api"):
            logger.info(
                f"SNMP unreachable for {device.get('name', host)}, "
                f"falling back to REST API polling"
            )
            result = await poll_via_rest_api(device)
        else:
            # Tidak ada REST API configured — kembalikan offline
            result = {
                "reachable": False,
                "ping": {"reachable": False, "avg": 0, "jitter": 0, "loss": 100},
                "system": {}, "cpu": 0,
                "memory": {"total": 0, "used": 0, "percent": 0},
                "interfaces": [], "traffic": {},
                "health": {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0},
            }

    now = datetime.now(timezone.utc).isoformat()

    # ── Offline grace period: don't mark offline on the FIRST failed poll ─────
    # Only mark offline after OFFLINE_GRACE_POLLS consecutive failures.
    # This prevents transient SNMP timeouts from causing false-offline alerts.
    consecutive_failures = device.get("consecutive_poll_failures", 0)
    old_status = device.get("status", "unknown")

    if result["reachable"]:
        new_status = "online"
        consecutive_failures = 0
    else:
        consecutive_failures += 1
        if consecutive_failures >= OFFLINE_GRACE_POLLS:
            new_status = "offline"
        else:
            # Grace period: keep current status (don't flip to offline yet)
            new_status = old_status if old_status in ("online", "offline") else "offline"
            logger.info(f"Poll failed for {device.get('name', host)} ({consecutive_failures}/{OFFLINE_GRACE_POLLS}), grace period active")

    update = {
        "status": new_status,
        "last_poll": now,
        "last_poll_data": result,
        "consecutive_poll_failures": consecutive_failures,
    }

    if result["reachable"] and result.get("system"):
        s = result["system"]
        health = result.get("health", {})
        update.update({
            "model": s.get("board_name", ""),
            "sys_name": s.get("sys_name", ""),
            "identity": s.get("identity", s.get("sys_name", "")),
            "architecture": s.get("architecture", ""),
            "ros_version": s.get("ros_version", ""),
            "uptime": s.get("uptime_formatted", ""),
            "serial": s.get("serial", ""),
            "cpu_load": result.get("cpu", 0),
            "memory_usage": result.get("memory", {}).get("percent", 0),
            "cpu_temp": health.get("cpu_temp", 0),
            "board_temp": health.get("board_temp", 0),
            "voltage": health.get("voltage", 0),
            "power": health.get("power", 0),
        })

    # ── SLA Event Recording: detect status transitions ────────────────────────
    # Compare new status vs stored status to record online/offline events
    if old_status != new_status and new_status in ("online", "offline"):
        try:
            await db.sla_events.insert_one({
                "device_id": did,
                "device_name": device.get("name", did),
                "event_type": new_status,     # "online" or "offline"
                "from_status": old_status,
                "timestamp": now,
            })
            logger.info(f"SLA event recorded: {device.get('name', did)} → {new_status}")
        except Exception as sla_err:
            logger.debug(f"SLA event write failed: {sla_err}")

    await db.devices.update_one({"id": did}, {"$set": update})

    # ── Detect ISP/INPUT interfaces via MikroTik API ──────────────────────────
    # Runs async after main poll; saves isp_interfaces to device doc for use
    # by dashboard/interfaces, traffic-history, and wallboard bandwidth queries.
    try:
        # Gunakan get_api_client dari module-level import (bukan routers.devices)
        mt = get_api_client(device)
        isp_ifaces = await mt.get_isp_interfaces()
        if isp_ifaces:
            await db.devices.update_one(
                {"id": did},
                {"$set": {"isp_interfaces": isp_ifaces}}
            )
    except Exception as isp_err:
        logger.debug(f"ISP interface detect skipped for {did}: {isp_err}")

    # Fire WhatsApp notifications if enabled

    try:
        from services.notification_service import check_and_notify
        await check_and_notify(device, result, update)
    except Exception as e:
        logger.debug(f"Notification check skipped: {e}")

    # ── Bandwidth: SNMP octets delta ATAU REST API precomputed ───────────────
    prev = await db.traffic_snapshots.find_one({"device_id": did})
    curr_traffic = result.get("traffic", {})
    ping_data    = result.get("ping", {})
    bw = {}

    poll_mode = result.get("poll_mode", "snmp")

    if poll_mode == "rest_api":
        # REST API mode: gunakan bandwidth langsung dari monitor-traffic
        bw = result.get("bw_precomputed", {})
    elif prev and curr_traffic:
        # SNMP mode: hitung bandwidth dari delta octets
        prev_t = prev.get("traffic", {})
        try:
            delta = max((datetime.fromisoformat(now) - datetime.fromisoformat(prev["timestamp"])).total_seconds(), 1)
        except Exception:
            delta = POLL_INTERVAL
        for iface, cv in curr_traffic.items():
            pv = prev_t.get(iface, {})
            if pv:
                ind  = max(0, cv["in_octets"]  - pv.get("in_octets",  0))
                outd = max(0, cv["out_octets"] - pv.get("out_octets", 0))
                if ind  > 2**62: ind  = 0
                if outd > 2**62: outd = 0
                bw[iface] = {
                    "download_bps": round((ind  * 8) / delta),
                    "upload_bps":   round((outd * 8) / delta),
                    "status": cv.get("status", "down"),
                }

    # ── Save ONE unified traffic_history record per cycle ────────────────────
    total_dl_bps = sum(v.get("download_bps", 0) for v in bw.values() if isinstance(v, dict))
    total_ul_bps = sum(v.get("upload_bps",   0) for v in bw.values() if isinstance(v, dict))

    snapshot = {
        "device_id": did,
        "timestamp": now,
        # Accurate per-interface bandwidth (requires prev snapshot for diff)
        "bandwidth": bw,
        # Top-level totals for backward-compat with older query paths
        "download_mbps": round(total_dl_bps / 1_000_000, 3),
        "upload_mbps":   round(total_ul_bps / 1_000_000, 3),
        # System metrics
        "cpu":            result.get("cpu", 0),
        "memory_percent": result.get("memory", {}).get("percent", 0),
        "ping_ms":        ping_data.get("avg", 0) or 0,
        "jitter_ms":      ping_data.get("jitter", 0) or 0,
    }
    try:
        await db.traffic_history.insert_one(snapshot)
        # Keep max 2880 records per device (24h at 30s interval)
        count = await db.traffic_history.count_documents({"device_id": did})
        if count > 2880:
            oldest = await db.traffic_history.find(
                {"device_id": did}, {"_id": 1}
            ).sort("timestamp", 1).limit(count - 2880).to_list(count - 2880)
            ids = [d["_id"] for d in oldest]
            if ids:
                await db.traffic_history.delete_many({"_id": {"$in": ids}})
    except Exception as hist_err:
        logger.debug(f"Traffic history write failed: {hist_err}")

    # ── Write to InfluxDB if configured ──────────────────────────────────────
    if bw:
        try:
            from services.metrics_service import write_device_metrics, is_enabled
            if is_enabled():
                metrics_payload = {
                    "cpu": result.get("cpu", 0),
                    "memory": result.get("memory", {}),
                    "ping": ping_data,
                    "health": result.get("health", {}),
                    "bandwidth": bw,
                }
                await asyncio.to_thread(
                    write_device_metrics, did, device.get("name", did), metrics_payload,
                )
        except Exception as e:
            logger.debug(f"InfluxDB write skipped: {e}")

    # ── Update current traffic snapshot (for next-cycle delta calculation) ───
    await db.traffic_snapshots.update_one(
        {"device_id": did},
        {"$set": {"device_id": did, "timestamp": now, "traffic": curr_traffic}},
        upsert=True
    )
    return result




async def polling_loop():
    """Background task: poll all devices every POLL_INTERVAL seconds."""
    while True:
        try:
            db = get_db()
            devices = await db.devices.find({}, {"_id": 0}).to_list(100)
            if devices:
                await asyncio.gather(*[poll_single_device(d) for d in devices], return_exceptions=True)
            # Cleanup data lama: simpan 31 hari agar tombol "Bulan" berfungsi
            # BUG FIX: sebelumnya 7 hari → data "Bulan" tidak pernah ada
            cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            await db.traffic_history.delete_many({"timestamp": {"$lt": cutoff}})
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll loop error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
