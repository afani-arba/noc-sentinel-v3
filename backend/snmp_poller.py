"""
snmp_poller.py — SNMP v2c Traffic Monitor (Async API)
======================================================
KRITIS: Gunakan pysnmp.hlapi.asyncio (ASYNC) bukan sync.
pysnmp-lextudio 6.x mengintegrasikan ASYNC API sebagai primary.
Sync nextCmd/bulkCmd TIDAK BEKERJA dengan lextudio 6.x.

Approach: GET per-index (1..max_index) mirip original noc-sentinel/snmp_service.py
yang terbukti bekerja. Lebih reliable dari WALK karena tidak perlu OID iteration.

Fix 2026-03-16: total rewrite pakai asyncio getCmd per-index.
"""
import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── OID Constants ─────────────────────────────────────────────────────────────
OID_SYS_DESCR        = "1.3.6.1.2.1.1.1.0"       # sysDescr (device version)
OID_SYS_UPTIME       = "1.3.6.1.2.1.1.3.0"       # sysUpTime
OID_IF_DESCR         = "1.3.6.1.2.1.2.2.1.2"     # ifDescr.{n}
OID_IF_NAME          = "1.3.6.1.2.1.31.1.1.1.1"  # ifName.{n}
OID_IF_HC_IN_OCTETS  = "1.3.6.1.2.1.31.1.1.1.6"  # ifHCInOctets.{n}  (64-bit)
OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10" # ifHCOutOctets.{n} (64-bit)
OID_IF_IN_OCTETS     = "1.3.6.1.2.1.2.2.1.10"    # ifInOctets.{n}    (32-bit)
OID_IF_OUT_OCTETS    = "1.3.6.1.2.1.2.2.1.16"    # ifOutOctets.{n}   (32-bit)
OID_IF_OPER_STATUS   = "1.3.6.1.2.1.2.2.1.8"     # ifOperStatus.{n}

# ── SMA State ─────────────────────────────────────────────────────────────────
_SMA_W = 3
_sma_dl: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_W)))
_sma_ul: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_W)))
_is_64bit: Dict[str, bool] = {}


def apply_sma(device_id: str, iface: str, dl: int, ul: int) -> tuple:
    _sma_dl[device_id][iface].append(dl)
    _sma_ul[device_id][iface].append(ul)
    return (
        int(sum(_sma_dl[device_id][iface]) / len(_sma_dl[device_id][iface])),
        int(sum(_sma_ul[device_id][iface]) / len(_sma_ul[device_id][iface])),
    )


def clear_sma_cache(device_id: str):
    _sma_dl.pop(device_id, None)
    _sma_ul.pop(device_id, None)


# ── Core Async SNMP GET ────────────────────────────────────────────────────────

async def _snmp_get(host: str, community: str, oid: str,
                    port: int = 161, timeout: int = 3) -> Optional[str]:
    """
    Single async SNMP GET untuk satu OID.
    Menggunakan pysnmp.hlapi.asyncio persis seperti original noc-sentinel.
    Return string value atau None jika gagal/tidak ada.
    """
    try:
        from pysnmp.hlapi.asyncio import (
            getCmd, SnmpEngine, CommunityData,
            UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity,
        )
        engine = SnmpEngine()
        result = await getCmd(
            engine,
            CommunityData(community, mpModel=1),
            UdpTransportTarget((host, port), timeout=timeout, retries=0),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        try:
            engine.closeDispatcher()
        except Exception:
            pass

        err_ind, err_st, _, var_binds = result
        if err_ind or err_st:
            return None

        for oid_obj, val in var_binds:
            v = str(val)
            if "NoSuchInstance" in v or "NoSuchObject" in v or "endOfMib" in v:
                return None
            return v.strip()

    except ImportError:
        logger.error("[SNMP] pysnmp tidak terinstall — pip install pysnmp-lextudio==6.2.0")
        return None
    except Exception as e:
        logger.debug(f"[SNMP] GET {host} OID={oid}: {type(e).__name__}: {e}")
        return None


# ── GET per-index walk ─────────────────────────────────────────────────────────

async def _snmp_get_indexed(host: str, community: str, base_oid: str,
                             max_index: int = 64, timeout: int = 3,
                             as_int: bool = False) -> Dict[int, object]:
    """
    Walk via GET per-index: coba OID.1 sampai OID.max_index.
    Approach dari original noc-sentinel yang terbukti bekerja.

    Batch parallel: 8 request per batch untuk efisiensi.
    Stop early jika batch kosong dan sudah ada hasil.
    """
    results = {}

    async def get_one(idx: int):
        val = await _snmp_get(host, community, f"{base_oid}.{idx}", timeout=timeout)
        if val is None:
            return None
        if as_int:
            try:
                return (idx, int(val))
            except (ValueError, TypeError):
                return None
        return (idx, val)

    batch_size = 8
    for batch_start in range(1, max_index + 1, batch_size):
        batch_end = min(batch_start + batch_size, max_index + 1)
        tasks = [get_one(i) for i in range(batch_start, batch_end)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        found_any = False
        for r in batch_results:
            if r and not isinstance(r, Exception):
                results[r[0]] = r[1]
                found_any = True

        # Stop early jika batch kosong dan sudah ada results (hemat waktu)
        if not found_any and results:
            break

    return results


# ── Interface Name Discovery ───────────────────────────────────────────────────

async def _get_ifnames(host: str, community: str,
                        timeout: int = 3) -> Dict[int, str]:
    """
    {ifIndex: name} dengan 3-level fallback.
    Level 1: ifDescr — universal (RFC 2863)
    Level 2: ifName  — MikroTik short name
    Level 3: Synthetic "if{n}" dari ifInOctets index
    """
    logger.warning(f"[SNMP DEBUG] {host}: walk ifDescr (GET per-index)...")
    r = await _snmp_get_indexed(host, community, OID_IF_DESCR, timeout=timeout)
    if r:
        logger.warning(
            f"[SNMP DEBUG] {host}: ifDescr OK → {len(r)} ifaces: "
            f"{list(r.values())[:5]}"
        )
        return r

    logger.warning(f"[SNMP DEBUG] {host}: ifDescr kosong, coba ifName...")
    r = await _snmp_get_indexed(host, community, OID_IF_NAME, timeout=timeout)
    if r:
        logger.warning(
            f"[SNMP DEBUG] {host}: ifName OK → {len(r)} ifaces: "
            f"{list(r.values())[:5]}"
        )
        return r

    logger.warning(f"[SNMP DEBUG] {host}: ifName kosong, coba synthetic...")
    r = await _snmp_get_indexed(host, community, OID_IF_IN_OCTETS,
                                  timeout=timeout, as_int=True)
    if r:
        synth = {idx: f"if{idx}" for idx in r}
        logger.warning(f"[SNMP DEBUG] {host}: synthetic OK → {len(synth)} ifaces")
        return synth

    logger.error(
        f"[SNMP DEBUG] {host}: SEMUA LEVEL GAGAL. "
        f"Cek: (1) community string di device, "
        f"(2) SNMP enabled di IP Services, "
        f"(3) port 161/UDP tidak diblokir firewall."
    )
    return {}


# ── Single Poll Cycle ──────────────────────────────────────────────────────────

async def _single_poll(host: str, community: str,
                        timeout: int = 4) -> Optional[Dict[str, Dict]]:
    """
    Satu siklus poll: ifnames + counters (parallel).
    Return {iface_name: {in_octets, out_octets}} atau None jika gagal.
    """
    names = await _get_ifnames(host, community, timeout=timeout)
    if not names:
        return None

    # Ambil semua counter parallel
    in64_task  = _snmp_get_indexed(host, community, OID_IF_HC_IN_OCTETS,
                                    timeout=timeout, as_int=True)
    out64_task = _snmp_get_indexed(host, community, OID_IF_HC_OUT_OCTETS,
                                    timeout=timeout, as_int=True)
    in64, out64 = await asyncio.gather(in64_task, out64_task)

    use64 = bool(in64)
    in_map, out_map = in64, out64

    if not use64:
        logger.debug(f"[SNMP] 64-bit HC kosong [{host}], fallback 32-bit...")
        in32_task  = _snmp_get_indexed(host, community, OID_IF_IN_OCTETS,
                                        timeout=timeout, as_int=True)
        out32_task = _snmp_get_indexed(host, community, OID_IF_OUT_OCTETS,
                                        timeout=timeout, as_int=True)
        in_map, out_map = await asyncio.gather(in32_task, out32_task)

    if not in_map:
        logger.warning(f"[SNMP DEBUG] {host}: counter walk kosong")
        return None

    _is_64bit[host] = use64
    logger.warning(
        f"[SNMP DEBUG] {host}: poll OK — "
        f"{len(names)} ifaces, {len(in_map)} counters, 64bit={use64}"
    )

    return {
        name: {
            "in_octets":  in_map.get(idx, 0),
            "out_octets": out_map.get(idx, 0),
        }
        for idx, name in names.items()
    }


# ── Ambil versi device via sysDescr ───────────────────────────────────────────

async def get_device_snmp_info(host: str, community: str = "public",
                                port: int = 161, timeout: int = 4) -> Dict:
    """
    Ambil info device via SNMP: sysDescr (berisi versi RouterOS),
    sysUpTime, dan jumlah interface.
    Digunakan untuk menampilkan info device di UI.
    """
    sys_descr, sys_uptime = await asyncio.gather(
        _snmp_get(host, community, OID_SYS_DESCR, port=port, timeout=timeout),
        _snmp_get(host, community, OID_SYS_UPTIME, port=port, timeout=timeout),
    )

    info = {"snmp_reachable": False, "sys_descr": "", "uptime_s": 0,
            "ros_version": "", "interface_count": 0}

    if sys_descr:
        info["snmp_reachable"] = True
        info["sys_descr"] = sys_descr.strip()

        # Parse ROS version dari sysDescr: "RouterOS 7.16.2 ..."
        import re
        m = re.search(r"(\d+\.\d+[\.\d]*)", sys_descr)
        if m:
            info["ros_version"] = m.group(1)

    if sys_uptime:
        try:
            ticks = int(sys_uptime)
            info["uptime_s"] = ticks // 100
        except (ValueError, TypeError):
            pass

    # Count interfaces
    if info["snmp_reachable"]:
        names = await _get_ifnames(host, community, timeout=timeout)
        info["interface_count"] = len(names)

    return info


# ── Main: Bandwidth Real-Time ──────────────────────────────────────────────────

async def get_snmp_traffic(
    host: str,
    community: str = "public",
    device_id: str = "",
    iface_filter: Optional[list] = None,
    snmp_timeout: int = 4,
    apply_smoothing: bool = True,
) -> Dict[str, Dict]:
    """
    Delta 1-detik: T1 → sleep(1) → T2 → bps = (T2-T1)*8.
    Menggunakan async getCmd per-index (sama seperti original noc-sentinel).
    """
    if not host:
        return {}
    try:
        t1 = await _single_poll(host, community, snmp_timeout)
        if not t1:
            return {}

        await asyncio.sleep(1)

        t2 = await _single_poll(host, community, snmp_timeout)
        if not t2:
            return {}

        CMAX    = (2 ** 64) if _is_64bit.get(host, True) else (2 ** 32)
        MAX_BPS = 400_000_000_000
        result  = {}

        for iface, d2 in t2.items():
            if iface_filter and iface not in iface_filter:
                continue
            d1 = t1.get(iface)
            if not d1:
                continue

            di = d2["in_octets"]  - d1["in_octets"]
            do = d2["out_octets"] - d1["out_octets"]
            if di < 0: di += CMAX
            if do < 0: do += CMAX

            dl = min(int(di * 8), MAX_BPS)
            ul = min(int(do * 8), MAX_BPS)

            if apply_smoothing and device_id:
                dl, ul = apply_sma(device_id, iface, dl, ul)

            result[iface] = {
                "download_bps": dl,
                "upload_bps":   ul,
                "status":       "up",
                "source":       "snmp",
            }

        if result:
            logger.warning(
                f"[SNMP DEBUG] {host}: traffic OK — {len(result)} ifaces active"
            )
        return result

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[SNMP] traffic error [{host}]: {e}")
        return {}


# ── Reachability Test ─────────────────────────────────────────────────────────

async def test_snmp_reachable(host: str, community: str = "public",
                               timeout: int = 3) -> bool:
    """Test apakah SNMP v2c dapat dijangkau — cek sysDescr."""
    result = await _snmp_get(host, community, OID_SYS_DESCR, timeout=timeout)
    return result is not None
