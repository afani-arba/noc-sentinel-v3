"""
Polling Engine — MikroTik REST API & RouterOS API Protocol.
Tidak menggunakan SNMP. Semua data diambil via MikroTik REST API (ROS 7+)
atau RouterOS API Protocol (ROS 6+).

Dioptimalkan untuk monitoring 100+ device secara bersamaan:
- MAX_CONCURRENT_POLLS: 20 (paralel, dibatasi semaphore)
- Timeout per device: 30s
- Interval polling: 30s
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from core.db import get_db
from mikrotik_api import get_host_only, get_api_client
import ping_service

logger = logging.getLogger(__name__)

POLL_INTERVAL        = 30    # Detik antar polling cycle
DEVICE_TIMEOUT       = 30    # Maks waktu per device (REST API + health)
OFFLINE_GRACE_POLLS  = 2     # Gagal berturut-turut sebelum tandai offline
MAX_CONCURRENT_POLLS = 20    # Paralel polling — aman untuk 100+ device


# ── Core: Poll device via MikroTik API ───────────────────────────────────────

async def poll_via_api(device: dict) -> dict:
    """
    Ambil data monitoring via MikroTik REST API (ROS 7+) atau RouterOS API Protocol (ROS 6+).
    Menghasilkan struktur data standar untuk disimpan ke DB.
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
    }

    try:
        mt = get_api_client(device)
        api_mode = device.get("api_mode", "rest")

        # ── Ambil semua data secara paralel ──────────────────────────────────
        async def _empty():
            return {}

        sys_res, identity_res, health_raw, ifaces_raw = await asyncio.gather(
            mt.get_system_resource(),
            mt._async_req("GET", "system/identity") if hasattr(mt, "_async_req") else _empty(),
            mt.get_system_health(),
            mt.list_interfaces(),
            return_exceptions=True,
        )

        # Bersihkan exceptions
        if isinstance(sys_res,      Exception): sys_res      = {}
        if isinstance(identity_res, Exception): identity_res = {}
        if isinstance(health_raw,   Exception): health_raw   = {}
        if isinstance(ifaces_raw,   Exception): ifaces_raw   = []

        # Jika tidak ada data sama sekali → device tidak bisa dijangkau
        if not sys_res and not identity_res:
            logger.warning(f"API tidak merespon untuk {device.get('name', '?')} [{device.get('ip_address', '?')}]")
            return EMPTY_RESULT

        # ── Identity (nama router) ────────────────────────────────────────────
        router_name = ""
        if isinstance(identity_res, dict):
            router_name = identity_res.get("name", "")
        if not router_name:
            router_name = device.get("name", device.get("ip_address", ""))

        # ── Sistem Info ───────────────────────────────────────────────────────
        sys_info = {}
        uptime_formatted = "N/A"
        uptime_seconds = 0

        if sys_res:
            import re
            board_name   = sys_res.get("board-name", "")
            ros_version  = sys_res.get("version", "")
            architecture = sys_res.get("architecture-name", "")

            # Parse uptime format ROS: "3d15h30m10s"
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

        # ── Health (suhu, voltage, power) ─────────────────────────────────────
        health = {
            "cpu_temp":   health_raw.get("cpu_temp",   0) if isinstance(health_raw, dict) else 0,
            "board_temp": health_raw.get("board_temp", 0) if isinstance(health_raw, dict) else 0,
            "voltage":    health_raw.get("voltage",    0) if isinstance(health_raw, dict) else 0,
            "power":      health_raw.get("power",      0) if isinstance(health_raw, dict) else 0,
        }

        # ── Interfaces ────────────────────────────────────────────────────────
        interfaces  = []
        running_ifaces = []
        for iface in (ifaces_raw if isinstance(ifaces_raw, list) else []):
            name     = iface.get("name", "")
            running  = iface.get("running", False)
            disabled = str(iface.get("disabled", "false")).lower() == "true"
            status   = "down" if disabled else ("up" if running else "down")
            interfaces.append({
                "index": iface.get(".id", ""),
                "name":  name,
                "status": status,
                "speed": 0,
            })
            if running and not disabled and name:
                running_ifaces.append(name)

        # ── Bandwidth via monitor-traffic ──────────────────────────────────────
        # Ambil bandwidth real-time untuk setiap interface yang running.
        # ROS 7+ (mode=rest): POST /rest/interface/monitor-traffic
        # ROS 6+ (mode=api):  get_interface_traffic() via API Protocol (port 8728)
        bw_precomputed = {}
        if running_ifaces:
            if api_mode == "rest" and hasattr(mt, "_async_req"):
                # ── ROS 7.x: REST API monitor-traffic ────────────────────────
                async def get_iface_bw_rest(iface_name):
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
                    except Exception as e:
                        logger.debug(f"REST monitor-traffic gagal untuk {iface_name}: {e}")
                    return None

                tasks = [get_iface_bw_rest(n) for n in running_ifaces[:16]]
                bw_results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in bw_results:
                    if r and not isinstance(r, Exception):
                        bw_precomputed[r[0]] = r[1]

            elif api_mode == "api":
                # ── ROS 6.x: Ambil raw bytes stats (1 koneksi, semua interface) ─
                # Delta bps akan dihitung di poll_single_device yang punya akses ke db.
                try:
                    cur_stats = await mt.get_all_interface_stats()  # {name: {rx-bytes, tx-bytes}}
                    # Simpan ke iface_stats_raw untuk diproses di poll_single_device
                    # bw_precomputed akan diisi di sana setelah delta dihitung
                    if cur_stats:
                        logger.debug(f"ROS6 raw stats: {device.get('name','?')} {len(cur_stats)} interfaces")
                    # Simpan cur_stats ke return value via bw_precomputed sementara
                    # (akan diproses oleh poll_single_device)
                    return {
                        "reachable":       True,
                        "poll_mode":       "api_protocol",
                        "ping":            {"reachable": True, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 0},
                        "system":          sys_info,
                        "cpu":             cpu_load,
                        "memory":          memory,
                        "interfaces":      interfaces,
                        "traffic":         {},
                        "health":          health,
                        "bw_precomputed":  {},           # akan diisi poll_single_device
                        "iface_stats_raw": cur_stats,   # raw bytes untuk delta calc
                        "running_ifaces":  running_ifaces,
                    }
                except Exception as e:
                    logger.warning(f"ROS6 get_all_interface_stats gagal untuk {device.get('name','?')}: {e}")

        mode_label = "rest_api" if api_mode == "rest" else "api_protocol"
        logger.info(
            f"Poll OK [{mode_label}]: {device.get('name', '?')} "
            f"cpu={cpu_load}% mem={memory['percent']}% "
            f"ifaces={len(running_ifaces)} bw={len(bw_precomputed)}"
        )

        return {
            "reachable":       True,
            "poll_mode":       mode_label,
            "ping":            {"reachable": True, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 0},
            "system":          sys_info,
            "cpu":             cpu_load,
            "memory":          memory,
            "interfaces":      interfaces,
            "traffic":         {},
            "health":          health,
            "bw_precomputed":  bw_precomputed,
            "iface_stats_raw": {},   # kosong untuk mode REST (tidak butuh delta)
            "running_ifaces":  running_ifaces,
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


async def poll_single_device(device: dict) -> dict:
    """
    Poll satu device via MikroTik API (REST atau API Protocol — tanpa SNMP).
    Update DB dengan status, metrics, SLA events, bandwidth history.
    """
    db  = get_db()
    did = device["id"]

    # -- Poll via MikroTik API ------------------------------------------------
    result = await poll_via_api(device)

    # -- Offline grace period: jangan tandai offline pada kegagalan pertama ----
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
            # Grace period: pertahankan status sekarang
            new_status = old_status if old_status in ("online", "offline") else "offline"
            logger.info(
                f"Poll gagal untuk {device.get('name', did)} "
                f"({consecutive_failures}/{OFFLINE_GRACE_POLLS}), grace period aktif"
            )

    now = datetime.now(timezone.utc).isoformat()

    update = {
        "status":                   new_status,
        "last_poll":                now,
        "last_poll_data":           result,
        "consecutive_poll_failures": consecutive_failures,
    }

    if result["reachable"] and result.get("system"):
        s      = result["system"]
        health = result.get("health", {})
        update.update({
            "model":        s.get("board_name", ""),
            "sys_name":     s.get("sys_name", ""),
            "identity":     s.get("identity", s.get("sys_name", "")),
            "architecture": s.get("architecture", ""),
            "ros_version":  s.get("ros_version", ""),
            "uptime":       s.get("uptime_formatted", ""),
            "serial":       s.get("serial", ""),
            "cpu_load":     result.get("cpu", 0),
            "memory_usage": result.get("memory", {}).get("percent", 0),
            "cpu_temp":     health.get("cpu_temp",   0),
            "board_temp":   health.get("board_temp", 0),
            "voltage":      health.get("voltage",    0),
            "power":        health.get("power",      0),
        })

    # -- SLA Event: catat transisi status online/offline -----------------------
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

    # -- Deteksi ISP interface via MikroTik API --------------------------------
    try:
        mt = get_api_client(device)
        isp_ifaces = await mt.get_isp_interfaces()
        if isp_ifaces:
            await db.devices.update_one(
                {"id": did},
                {"$set": {"isp_interfaces": isp_ifaces}}
            )
    except Exception as isp_err:
        logger.debug(f"ISP interface detect skip untuk {did}: {isp_err}")

    # -- Notifikasi WhatsApp ---------------------------------------------------
    try:
        from services.notification_service import check_and_notify
        await check_and_notify(device, result, update)
    except Exception as e:
        logger.debug(f"Notification skip: {e}")

    # -- Bandwidth: ROS7 dari bw_precomputed, ROS6 dari delta iface_stats_raw ----
    ping_data = result.get("ping", {})
    bw = result.get("bw_precomputed", {})

    # ROS6: hitung delta bps dari raw bytes (iface_stats_raw dari poll_via_api)
    iface_stats_raw = result.get("iface_stats_raw", {})
    if iface_stats_raw and not bw:
        try:
            now_ts      = datetime.now(timezone.utc).timestamp()
            running_set = set(result.get("running_ifaces", []))

            # Ambil snapshot sebelumnya dari DB
            snap_doc  = await db.traffic_snapshots.find_one({"device_id": did}, {"_id": 0})
            prev_stats = snap_doc.get("iface_bytes", {}) if snap_doc else {}
            prev_ts    = snap_doc.get("ts")            if snap_doc else None

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
                    bw[iface_name] = {
                        "download_bps": int((rx_delta * 8) / elapsed),
                        "upload_bps":   int((tx_delta * 8) / elapsed),
                        "status":       "up",
                    }
                logger.info(
                    f"ROS6 delta bw OK: {device.get('name','?')} "
                    f"elapsed={elapsed:.1f}s bw={len(bw)} ifaces"
                )
        except Exception as e:
            logger.warning(f"ROS6 delta calc gagal untuk {device.get('name','?')}: {e}")
    # -- Simpan ke traffic_history (untuk grafik) ──────────────────────────────
    total_dl_bps = sum(v.get("download_bps", 0) for v in bw.values() if isinstance(v, dict))
    total_ul_bps = sum(v.get("upload_bps",   0) for v in bw.values() if isinstance(v, dict))

    snapshot = {
        "device_id":      did,
        "timestamp":      now,
        "bandwidth":      bw,
        "download_mbps":  round(total_dl_bps / 1_000_000, 3),
        "upload_mbps":    round(total_ul_bps / 1_000_000, 3),
        "cpu":            result.get("cpu", 0),
        "memory_percent": result.get("memory", {}).get("percent", 0),
        "ping_ms":        ping_data.get("avg",    0) or 0,
        "jitter_ms":      ping_data.get("jitter", 0) or 0,
    }
    try:
        await db.traffic_history.insert_one(snapshot)
        # Pertahankan maks 2880 record per device (24h × 30s interval)
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

    # -- Tulis ke InfluxDB (opsional) ─────────────────────────────────────────
    if bw:
        try:
            from services.metrics_service import write_device_metrics, is_enabled
            if is_enabled():
                metrics_payload = {
                    "cpu":       result.get("cpu", 0),
                    "memory":    result.get("memory", {}),
                    "ping":      ping_data,
                    "health":    result.get("health", {}),
                    "bandwidth": bw,
                }
                await asyncio.to_thread(
                    write_device_metrics, did, device.get("name", did), metrics_payload,
                )
        except Exception as e:
            logger.debug(f"InfluxDB write skip: {e}")

    # -- Update traffic snapshot (simpan iface_bytes untuk delta ROS6 berikutnya) -
    snap_update = {"device_id": did, "timestamp": now, "traffic": {}}
    if iface_stats_raw:
        # ROS6: simpan raw bytes untuk kalkulasi delta cycle berikutnya
        snap_update["iface_bytes"] = iface_stats_raw
        snap_update["ts"]          = datetime.now(timezone.utc).timestamp()
    await db.traffic_snapshots.update_one(
        {"device_id": did},
        {"$set": snap_update},
        upsert=True
    )

    return result


# ── Polling Loop: jalankan polling semua device setiap POLL_INTERVAL detik ───

async def polling_loop():
    """
    Background task: poll semua device setiap POLL_INTERVAL detik.
    Semaphore membatasi concurrency agar tidak overload server maupun network.
    Optimal untuk 100+ device MikroTik.
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
        start = asyncio.get_event_loop().time()
        try:
            db      = get_db()
            devices = await db.devices.find({}, {"_id": 0}).to_list(None)
            if devices:
                logger.debug(f"Polling {len(devices)} device (max {MAX_CONCURRENT_POLLS} paralel)...")
                await asyncio.gather(
                    *[poll_with_semaphore(d) for d in devices],
                    return_exceptions=True
                )

            # Bersihkan data lama: simpan 31 hari agar fitur "Bulan" berfungsi
            cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            await db.traffic_history.delete_many({"timestamp": {"$lt": cutoff}})

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll loop error: {e}")

        # Tunggu interval berikutnya (dikurangi waktu yang sudah terpakai)
        elapsed    = asyncio.get_event_loop().time() - start
        sleep_time = max(1, POLL_INTERVAL - elapsed)
        await asyncio.sleep(sleep_time)
