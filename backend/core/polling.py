import asyncio
import logging
import re
import random
from datetime import datetime, timezone, timedelta

from core.db import get_db
from mikrotik_api import get_host_only, get_api_client, discover_device
import ping_service

logger = logging.getLogger(__name__)

# ── Polling Constants (API Only) ─────────────────────────────────────────────
TRAFFIC_POLL_INTERVAL = 5     # Detik antar siklus polling traffic (5 detik)
SYSTEM_POLL_INTERVAL  = 60    # Detik antar siklus polling system (CPU, RAM, dsb)
DEVICE_TIMEOUT        = 10    # Maks waktu per device
OFFLINE_GRACE_POLLS   = 3     # Kegagalan beruntun sebelum tandai offline
MAX_CONCURRENT_POLLS  = 50    # Semaphore (Worker pool size)

from typing import Dict, Any

# Global trackers
_last_sys_poll: Dict[str, float] = {}  # device_id -> timestamp (float)
_device_tick: Dict[str, int]   = {}  # device_id -> int (untuk skip cycle offline)

# Virtual Interface Types to ignore
_VIRTUAL_IFACE_TYPES = {
    "bridge", "vlan", "pppoe-out", "pppoe-in", "l2tp", "pptp", "ovpn-client",
    "ovpn-server", "sstp-client", "sstp-server", "gre", "eoip", "eoipv6",
    "veth", "wireguard", "loopback", "6to4", "ipip", "ipip6", "dummy"
}
_VIRTUAL_IFACE_PREFIXES = ("lo", "docker", "veth", "tun", "tap", "<")

_SFP_IFACE_TYPES = {
    "sfp-sfpplus", "sfpplus", "sfp", "10g-sfp", "10gbase-x",
    "qsfp", "qsfp+", "qsfp28", "combo", "sfp-sfpplus-combo",
    "10gsfp-sfpplus", "sfp28", "25g-sfp28", "40g-qsfp", "100g-qsfp28",
}
_SFP_IFACE_PREFIXES = ("sfp", "sfpplus", "qsfp", "combo")


# ══════════════════════════════════════════════════════════════════════════════
# Auto-Discovery
# ══════════════════════════════════════════════════════════════════════════════
async def _ensure_api_mode(device: dict, db) -> dict:
    if device.get("api_mode") in ("rest", "api"):
        return device

    logger.info(f"Auto-discover: {device.get('name','?')} [{device.get('ip_address','?')}]...")
    disc = await discover_device(device)

    if disc["success"]:
        upf = {
            "api_mode":    disc["api_mode"],
            "ros_version": disc.get("ros_version", ""),
            "model":       disc.get("board_name", "") or device.get("model", ""),
        }
        if disc["api_mode"] == "rest":
            upf["use_https"] = disc.get("use_https", False)
            if disc.get("rest_port"):
                upf["api_port"] = disc["rest_port"]
        elif disc.get("api_port"):
            upf["api_port"] = disc["api_port"]

        await db.devices.update_one({"id": device["id"]}, {"$set": upf})
        device = {**device, **upf}
        logger.info(f"Discovery OK: {device.get('name','?')} → mode={disc['api_mode']}")
    else:
        logger.warning(f"Discovery GAGAL: {device.get('name','?')} — gunakan mode default 'rest'")
        device = {**device, "api_mode": "rest"}

    return device


# ══════════════════════════════════════════════════════════════════════════════
# API Data Parsing & Fetch
# ══════════════════════════════════════════════════════════════════════════════

async def poll_via_api(device: dict, fetch_system: bool) -> dict:
    mt       = get_api_client(device)
    api_mode = device.get("api_mode", "rest")
    dev_name = device.get("name", device.get("ip_address", "?"))
    
    if api_mode == "api":
        # ROS6 (Legacy API) tidak mentolerir banyak koneksi bersamaan.
        # Kita gunakan metode khusus yang berjalan dalam SATU koneksi TCP
        res_dict = await mt.get_polling_data(fetch_system)
    else:
        # 1. Ambil ifaces terlebih dahulu untuk mencari antarmuka ISP1
        ifaces_raw = await mt.list_interfaces()
        
        isp1_name = ""
        for iface in ifaces_raw:
            if not isinstance(iface, dict): continue
            name = iface.get("name", "")
            comment = str(iface.get("comment", "") or "").lower()
            if "isp1" in name.lower() or "1" in comment:
                isp1_name = name
                break
        
        # 2. Kumpulkan task API lainnya 
        tasks = {
            "ping": mt.ping_host("8.8.8.8", count=3, interface=isp1_name)
        }
        
        # Selective Polling: Hanya ambil sistem berat setiap x detik
        if fetch_system:
            tasks["sys"]     = mt.get_system_resource()
            tasks["health"]  = mt.get_system_health()
            tasks["pppoe"]   = mt.list_pppoe_active()
            tasks["hotspot"] = mt.list_hotspot_active()

        # ROS7 REST API mendukung HTTP connection pool (bisa serempak)
        results = await asyncio.gather(*(tasks.values()), return_exceptions=True)
        res_dict = dict(zip(tasks.keys(), results))
        res_dict["ifaces"] = ifaces_raw
    
    ifaces_raw = res_dict.get("ifaces", [])
    if isinstance(ifaces_raw, Exception): ifaces_raw = []
    
    if not isinstance(ifaces_raw, list) or len(ifaces_raw) == 0:
        raise Exception("Gagal mengambil data interface dari API (timeout or auth error)")

    # ── Parse Interfaces (Traffic + ISP + Status) ─────────────────────────────
    # Ini 100% dari API yang berjalan realtime (rx-byte dan tx-byte)
    interfaces = []
    running_ifaces = []
    isp_detected = []
    iface_stats_raw = {}
    
    _ISP_KEYWORDS = (
        "isp", *[f"isp{i}" for i in range(1, 21)],
        "wan", *[f"wan{i}" for i in range(1, 21)],
        "input", *[f"input{i}" for i in range(1, 21)],
        "uplink", "upstream", "internet", "gateway",
    )

    for iface in ifaces_raw:
        if not isinstance(iface, dict): continue
        name     = iface.get("name", "")
        if not name: continue
        itype    = str(iface.get("type", "")).lower()
        running  = str(iface.get("running", "false")).lower() == "true"
        disabled = str(iface.get("disabled", "false")).lower() == "true"
        comment  = str(iface.get("comment", "") or "").lower()

        is_sfp = itype in _SFP_IFACE_TYPES or name.lower().startswith(_SFP_IFACE_PREFIXES)
        if is_sfp and not disabled:
            running = True  # Asumsi SFP bonded / selalu aktif jika tak disable

        status = "down" if disabled else ("up" if running else "down")
        is_virtual = itype in _VIRTUAL_IFACE_TYPES or name.lower().startswith(_VIRTUAL_IFACE_PREFIXES) or name.startswith("<")
        
        # Deteksi ISP1 secara spesifik berdasarkan nama "isp1" atau comment mengandung "1"
        is_isp1 = False
        if "isp1" in name.lower() or "1" in comment:
            is_isp1 = True

        if any(kw in comment for kw in _ISP_KEYWORDS) or is_isp1:
            isp_detected.append(name)
            
        interfaces.append({
            "index":   iface.get(".id", ""),
            "name":    name,
            "type":    itype,
            "status":  status,
            "speed":   0,
            "virtual": is_virtual,
            "is_sfp":  is_sfp,
            "is_isp1": is_isp1,
        })
        
        if not is_virtual:
            rx_bytes = int(iface.get("rx-byte", 0) or 0)
            tx_bytes = int(iface.get("tx-byte", 0) or 0)
            iface_stats_raw[name] = {"rx-bytes": rx_bytes, "tx-bytes": tx_bytes}
            if running and not disabled:
                running_ifaces.append(name)
                
    # ── Parse System (jika difetch) ───────────────────────────────────────────
    sys_info = {}
    cpu_load = 0
    memory = {"total": 0, "used": 0, "percent": 0}
    health = {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0}
    pppoe_active = 0
    hotspot_active = 0
    
    if fetch_system:
        # System Resource
        sys_res = res_dict.get("sys")
        if isinstance(sys_res, dict) and sys_res:
            cpu_load = int(str(sys_res.get("cpu-load", "0")).rstrip("%") or "0")
            total_mem = int(sys_res.get("total-memory", 0) or 0)
            free_mem = int(sys_res.get("free-memory", 0) or 0)
            used_mem = max(0, total_mem - free_mem)
            if total_mem > 0:
                memory = {"total": total_mem, "used": used_mem, "percent": round((used_mem / total_mem) * 100)}
                
            uptime_raw = str(sys_res.get("uptime", "") or "")
            uptime_sec = 0
            fmt = "N/A"
            try:
                d_m = re.search(r"(\d+)d", uptime_raw)
                d = int(d_m.group(1)) if d_m else 0
                h_m = re.search(r"(\d+)h", uptime_raw)
                h = int(h_m.group(1)) if h_m else 0
                m_m = re.search(r"(\d+)m", uptime_raw)
                m = int(m_m.group(1)) if m_m else 0
                s_m = re.search(r"(\d+)s", uptime_raw)
                sec = int(s_m.group(1)) if s_m else 0
                uptime_sec = d * 86400 + h * 3600 + m * 60 + sec
                fmt = f"{d}d {h}h {m}m"
            except:
                fmt = uptime_raw or "N/A"

            sys_info = {
                "sys_name":         sys_res.get("board-name", dev_name),
                "board_name":       sys_res.get("board-name", ""),
                "identity":         sys_res.get("identity", dev_name), # Akan di override bila ada sys identity
                "ros_version":      sys_res.get("version", ""),
                "architecture":     sys_res.get("architecture-name", ""),
                "uptime_formatted": fmt,
                "uptime_seconds":   uptime_sec,
                "serial":           "",
                "firmware":         sys_res.get("version", ""),
            }

        # Health
        health_raw = res_dict.get("health")
        if isinstance(health_raw, dict):
            health = {
                "cpu_temp":   float(health_raw.get("cpu_temp", 0) or 0),
                "board_temp": float(health_raw.get("board_temp", 0) or 0),
                "voltage":    float(health_raw.get("voltage", 0) or 0),
                "power":      float(health_raw.get("power", 0) or 0),
            }
            if health_raw.get("sfp_temp"): health["sfp_temp"] = float(health_raw["sfp_temp"])
            if health_raw.get("switch_temp"): health["switch_temp"] = float(health_raw["switch_temp"])
            
        # Pppoe & Hotspot
        pppoe_res = res_dict.get("pppoe")
        hotspot_res = res_dict.get("hotspot")
        if isinstance(pppoe_res, list): pppoe_active = len(pppoe_res)
        if isinstance(hotspot_res, list): hotspot_active = len(hotspot_res)

        # Coba ambil identity di ROS7 jika sys_info minim
        if not sys_info and api_mode == "rest" and hasattr(mt, "_async_req"):
            try:
                ir = await mt._async_req("GET", "system/identity")
                if isinstance(ir, dict) and "name" in ir:
                    sys_info["identity"] = ir["name"]
                    sys_info["sys_name"] = ir["name"]
            except Exception:
                pass


    # ── Parse Ping (Latency & Jitter RFC 1889) ──
    ping_raw = res_dict.get("ping", [])
    if isinstance(ping_raw, Exception): ping_raw = []
    
    ping_data = {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}
    if isinstance(ping_raw, list) and len(ping_raw) > 0:
        latencies = []
        for p in ping_raw:
            if isinstance(p, dict) and p.get("status") != "timeout" and p.get("time"):
                t_str = str(p.get("time"))
                val = 0.0
                try:
                    import re
                    s_m = re.search(r"([\d\.]+)s", t_str)
                    ms_m = re.search(r"([\d\.]+)ms", t_str)
                    us_m = re.search(r"([\d\.]+)us", t_str)
                    
                    matched = False
                    if s_m:
                        val += float(s_m.group(1)) * 1000
                        matched = True
                    if ms_m:
                        val += float(ms_m.group(1))
                        matched = True
                    if us_m:
                        val += float(us_m.group(1)) / 1000
                        matched = True
                        
                    if not matched:
                        val = float(t_str)
                        
                    latencies.append(val)
                except Exception:
                    continue
        
        if latencies:
            loss = round(((len(ping_raw) - len(latencies)) / len(ping_raw)) * 100)
            avg = sum(latencies) / len(latencies)
            # RFC 1889 style jitter calculation
            jitter = 0
            if len(latencies) > 1:
                jit_acc = 0
                for i in range(1, len(latencies)):
                    diff = abs(latencies[i] - latencies[i-1])
                    jit_acc += (diff - jit_acc) / 16.0
                jitter = jit_acc
            
            ping_data = {
                "reachable": True,
                "min": round(min(latencies), 1),
                "avg": round(avg, 1),
                "max": round(max(latencies), 1),
                "jitter": round(jitter, 1),
                "loss": loss
            }


    return {
        "reachable":       True,
        "poll_mode":       f"{api_mode}_api_only",
        "poll_source":     "api_delta",
        "ping":            ping_data,
        "system":          sys_info,
        "cpu":             cpu_load,
        "memory":          memory,
        "interfaces":      interfaces,
        "traffic":         {},
        "health":          health,
        "bw_precomputed":  {},
        "iface_stats_raw": iface_stats_raw,
        "running_ifaces":  running_ifaces,
        "isp_detected":    isp_detected,
        "pppoe_active":    pppoe_active,
        "hotspot_active":  hotspot_active,
        "system_fetched":  fetch_system
    }


# ══════════════════════════════════════════════════════════════════════════════
# Device Orchestrator
# ══════════════════════════════════════════════════════════════════════════════

async def poll_single_device(device: dict) -> dict:
    db  = get_db()
    did = device["id"]
    now_ts = asyncio.get_running_loop().time()
    
    # ── Tentukan Selective Polling ───────────────────────────────────────────
    last_sys = _last_sys_poll.get(did, 0)
    fetch_system = (now_ts - last_sys) >= SYSTEM_POLL_INTERVAL
    
    # Auto-discover jika perlu
    device = await _ensure_api_mode(device, db)

    try:
        result = await asyncio.wait_for(poll_via_api(device, fetch_system), timeout=25.0)
        
        ping_data = result.get("ping", {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100})
        real_ping_ms = ping_data.get("avg", 0)
        
        if fetch_system and result["reachable"]:
            _last_sys_poll[did] = now_ts
            
    except Exception as e:
        logger.error(f"[CRITICAL POLL FAILURE] API poll gagal {device.get('name', '?')} ({device.get('ip_address')}): {e.__class__.__name__} - {str(e)}")
        # Tambahkan default variables yang dibutuh jika throw exception
        ping_data = {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}
        real_ping_ms = 0
        result = {"reachable": False, "ping": ping_data}

    old_status = device.get("status", "unknown")
    failure_key = f"{did}_fails"
    consecutive_failures = int(_device_tick.get(failure_key, device.get("consecutive_poll_failures") or 0) or 0)

    if result["reachable"]:
        new_status = "online"
        consecutive_failures = 0
    else:
        consecutive_failures += 1
        new_status = "offline" if consecutive_failures >= OFFLINE_GRACE_POLLS else old_status

    _device_tick[failure_key] = consecutive_failures
    now_iso = datetime.now(timezone.utc).isoformat()

    # Gabung data jika poll sebagian
    update = {
        "status": new_status,
        "last_poll": now_iso,
        "consecutive_poll_failures": consecutive_failures,
    }

    if result["reachable"]:
        # Update system/CPU info hanya jika system_fetched=True
        if result.get("system_fetched"):
            update["last_poll_data"] = result
            
            s = result.get("system")
            if not isinstance(s, dict): s = {}
            health = result.get("health")
            if not isinstance(health, dict): health = {}
            memory = result.get("memory")
            if not isinstance(memory, dict): memory = {}

            update.update({
                "model":          s.get("board_name", ""),
                "sys_name":       s.get("sys_name", ""),
                "identity":       s.get("identity", s.get("sys_name", "")),
                "architecture":   s.get("architecture", ""),
                "ros_version":    s.get("ros_version", ""),
                "uptime":         s.get("uptime_formatted", ""),
                "uptime_seconds": s.get("uptime_seconds", 0),
                "serial":         s.get("serial", ""),
                "cpu_load":       result.get("cpu", 0),
                "memory_usage":   memory.get("percent", 0),
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
                "timestamp":   now_iso,
            })
        except Exception:
            pass

    if update:
        await db.devices.update_one({"id": did}, {"$set": update})

    # ── ISP Interface List Update ─────────────────────────────────────────────
    isp_in_poll = result.get("isp_detected", [])
    if isp_in_poll and result["reachable"]:
        if set(isp_in_poll) != set(device.get("isp_interfaces", [])):
            await db.devices.update_one({"id": did}, {"$set": {"isp_interfaces": isp_in_poll}})

    isp_for_bw = isp_in_poll or device.get("isp_interfaces", [])

    # ── ICMP Ping ─────────────────────────────────────────────────────────────
    ping_data = result.get("ping", {})
    real_ping_ms = ping_data.get("avg", 0) or 0
    if not real_ping_ms and result["reachable"]:
        try:
            ip_only = get_host_only(device.get("ip_address", ""))
            if ip_only:
                pr = await ping_service.ping_host(ip_only, count=1, timeout=1.5)
                real_ping_ms = pr.get("avg", 0) or 0
                ping_data = pr
        except Exception:
            pass

    # ── Bandwidth Kalkulasi Akurat (Delta Counter) ────────────────────────────
    bw = {}
    iface_stats_raw = result.get("iface_stats_raw", {})
    if iface_stats_raw and result["reachable"]:
        now_ts_real = datetime.now(timezone.utc).timestamp()
        snap_doc = await db.traffic_snapshots.find_one({"device_id": did}, {"_id": 0})
        prev_stats = snap_doc.get("iface_bytes", {}) if snap_doc else {}
        prev_ts = snap_doc.get("ts") if snap_doc else None

        if prev_stats and prev_ts:
            elapsed = max(now_ts_real - prev_ts, 1.0)
            running_set = set(result.get("running_ifaces", []))
            for iface_name, cur in iface_stats_raw.items():
                if iface_name not in running_set:
                    continue
                prev = prev_stats.get(iface_name)
                if not prev:
                    continue
                
                # Check Counter Wrap 64-bit
                rx_cur = cur.get("rx-bytes", 0)
                tx_cur = cur.get("tx-bytes", 0)
                rx_prev = prev.get("rx-bytes", 0)
                tx_prev = prev.get("tx-bytes", 0)
                
                if rx_cur < rx_prev: rx_delta = (rx_cur + (2**64)) - rx_prev
                else: rx_delta = rx_cur - rx_prev
                
                if tx_cur < tx_prev: tx_delta = (tx_cur + (2**64)) - tx_prev
                else: tx_delta = tx_cur - tx_prev
                
                dl_bps = int((rx_delta * 8) / elapsed)
                ul_bps = int((tx_delta * 8) / elapsed)
                
                # Saring abnormal jump akibat reset
                if dl_bps > 100_000_000_000 or ul_bps > 100_000_000_000:
                    dl_bps, ul_bps = 0, 0

                bw[iface_name] = {
                    "download_bps": dl_bps,
                    "upload_bps":   ul_bps,
                    "status":       "up",
                    "source":       "api_delta"
                }

        # Update cache Snapshot selalu jika online
        await db.traffic_snapshots.update_one(
            {"device_id": did}, 
            {"$set": {
                "device_id": did,
                "ts": now_ts_real, 
                "iface_bytes": iface_stats_raw
            }}, 
            upsert=True
        )

    # ── Metric Aggregation ────────────────────────────────────────────────────
    if not result["reachable"] or not bw:
        return result

    isp_bw = {}
    for iname in isp_for_bw:
        d = bw.get(iname)
        if isinstance(d, dict):
            isp_bw[iname] = d

    eff_dl = sum(v.get("download_bps", 0) for v in (isp_bw.values() if isp_bw else bw.values()) if isinstance(v, dict))
    eff_ul = sum(v.get("upload_bps", 0) for v in (isp_bw.values() if isp_bw else bw.values()) if isinstance(v, dict))
    
    # Hanya update grafik riwayat secara periodik untuk hemat Disk I/O.
    # Namun data snapshot selalu up to date di DB trafik snapshot.
    mem = result.get("memory")
    mem_dict = mem if isinstance(mem, dict) else {}
    history_record = {
        "device_id":      did,
        "timestamp":      now_iso,
        "bandwidth":      bw,
        "isp_bandwidth":  isp_bw,
        "download_mbps":  round(float(max(0, int(eff_dl))) / 1000000.0, 3),
        "upload_mbps":    round(float(max(0, int(eff_ul))) / 1000000.0, 3),
        "cpu":            int(result.get("cpu", 0) or 0),
        "memory_percent": int(mem_dict.get("percent", 0) or 0),
        "ping_ms":        round(float(real_ping_ms or 0), 1),
        "jitter_ms":      float(ping_data.get("jitter", 0) if isinstance(ping_data, dict) else 0),
        "poll_source":    "api_delta",
    }
    
    # Tulis history setiap kali polling untuk Realtime Chart
    try:
        await db.traffic_history.insert_one(history_record)
    except Exception:
        pass

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Polling Loop Daemon
# ══════════════════════════════════════════════════════════════════════════════

async def polling_loop():
    """
    Background loop: poll device (traffic 5s, system 60s).
    Menggunakan Concurrency Limit (Semaphore) & Jitter.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_POLLS)

    async def poll_with_semaphore_and_jitter(dev, index):
        # ── Concurrency Limit & Jitter ──
        # Menambah delai kecil agar tidak 100 router API call persis di ms yang sama
        jitter_sec = 0.05 * (index % 20)  # max 1 detik distribusi
        await asyncio.sleep(jitter_sec)
        
        async with semaphore:
            try:
                await asyncio.wait_for(poll_single_device(dev), timeout=DEVICE_TIMEOUT)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.error(f"Poll error untuk {dev.get('name', '?')}: {e}")

    while True:
        start_time = asyncio.get_running_loop().time()
        try:
            db = get_db()
            devices = await db.devices.find({}, {"_id": 0}).to_list(None)
            
            if devices:
                # Fix: kita tidak boleh skip device yang sedang dites jika statusnya tetap offline abadi
                to_poll = devices
                # for d in devices:
                #    did = d.get("id")
                #    if not did: continue
                #    fails = _device_tick.get(f"{did}_fails", d.get("consecutive_poll_failures") or 0)
                #    fails_int = int(fails or 0)
                #    if fails_int >= 5:
                #        # Lewati 4 siklus sebelum mencoba ulang
                #        skip_mod = fails_int % 5
                #        if skip_mod != 0:
                #            _device_tick[f"{did}_fails"] = fails_int + 1
                #            continue
                #    to_poll.append(d)

                tasks = [
                    poll_with_semaphore_and_jitter(d, i)
                    for i, d in enumerate(to_poll)
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

            # Cleanup data usang
            cutoff_snap = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
            await db.traffic_snapshots.delete_many({"ts": {"$lt": cutoff_snap}})
            
            # Membatasi storage limit untuk history berfrekuensi tinggi
            cutoff_hist = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            await db.traffic_history.delete_many({"timestamp": {"$lt": cutoff_hist}})
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll loop fatal error: {e}")

        elapsed = asyncio.get_running_loop().time() - start_time
        sleep_time = max(1.0, float(TRAFFIC_POLL_INTERVAL - elapsed))
        await asyncio.sleep(sleep_time)

