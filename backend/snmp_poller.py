"""
snmp_poller.py — SNMP v2c Traffic Monitor (Async API)
======================================================
KRITIS: pakai pysnmp.hlapi.asyncio (ASYNC) — pysnmp-lextudio 6.x.
Approach: GET per-index (1..max_index) via SATU SnmpEngine bersama.
Identik dengan original noc-sentinel/snmp_service.py yang terbukti bekerja.

Bug sebelumnya (fix 2026-03-16):
  _snmp_get_indexed membuat engine baru per-GET call + closeDispatcher() concurrent
  → race condition merusak asyncio internal dispatcher
  → semua GET return kosong dalam ~1ms meski device SNMP OK
  Fix: satu SnmpEngine dibuat di _snmp_get_indexed, di-reuse semua get_one() calls.
"""
import asyncio
import logging
import re
from collections import defaultdict, deque
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── OID Constants ─────────────────────────────────────────────────────────────
OID_SYS_DESCR        = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME         = "1.3.6.1.2.1.1.5.0"
OID_SYS_UPTIME       = "1.3.6.1.2.1.1.3.0"
OID_IF_DESCR         = "1.3.6.1.2.1.2.2.1.2"
OID_IF_NAME          = "1.3.6.1.2.1.31.1.1.1.1"
OID_IF_HC_IN_OCTETS  = "1.3.6.1.2.1.31.1.1.1.6"
OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10"
OID_IF_IN_OCTETS     = "1.3.6.1.2.1.2.2.1.10"
OID_IF_OUT_OCTETS    = "1.3.6.1.2.1.2.2.1.16"

# ── SMA State ─────────────────────────────────────────────────────────────────
_SMA_W = 3
_sma_dl: Dict = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_W)))
_sma_ul: Dict = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_W)))
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


# ── GET per-index walk (SATU engine bersama) ───────────────────────────────────

async def _snmp_get_indexed(host: str, community: str, base_oid: str,
                             max_index: int = 64, timeout: int = 3,
                             as_int: bool = False) -> dict:
    """
    Walk via GET per-index menggunakan SATU SnmpEngine bersama.
    Identik dengan original noc-sentinel/snmp_service.py:snmp_get_indexed().

    KRITIS: engine dibuat SEKALI di sini, di-reuse semua concurrent get_one() calls.
    Bukan satu engine per-GET — itu yang menyebabkan bug silent fail sebelumnya.
    """
    try:
        from pysnmp.hlapi.asyncio import (
            getCmd, SnmpEngine, CommunityData,
            UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity,
        )
    except ImportError:
        logger.error("[SNMP] pysnmp tidak terinstall — pip install pysnmp-lextudio==6.2.0")
        return {}

    engine = SnmpEngine()  # ← SATU engine, dibuat sekali untuk semua GETs
    results = {}

    async def get_one(idx: int):
        oid = f"{base_oid}.{idx}"
        try:
            result = await getCmd(
                engine,                               # reuse engine yang sama
                CommunityData(community, mpModel=1),
                UdpTransportTarget((host, 161), timeout=timeout, retries=0),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
            err_ind, err_st, _, var_binds = result
            if err_ind or err_st:
                return None
            for _, val in var_binds:
                v = str(val)
                if "NoSuchInstance" in v or "NoSuchObject" in v:
                    return None
                if as_int:
                    try:
                        return (idx, int(v))
                    except (ValueError, TypeError):
                        return None
                return (idx, v.strip())
        except Exception as e:
            logger.debug(f"[SNMP] {host} idx={idx}: {e}")
            return None

    # Batch parallel: 8 request per batch (seperti original)
    batch_size = 8
    for batch_start in range(1, max_index + 1, batch_size):
        batch_end = min(batch_start + batch_size, max_index + 1)
        tasks = [get_one(i) for i in range(batch_start, batch_end)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        found_any = False
        for r in batch_results:
            if r and not isinstance(r, Exception):
                results[int(r[0])] = r[1]
                found_any = True

        # Stop early jika batch kosong DAN sudah punya results (seperti original)
        if not found_any and results:
            break

    try:
        engine.closeDispatcher()
    except Exception:
        pass

    return results


# ── Single SNMP GET (untuk sysDescr etc) ──────────────────────────────────────

async def _snmp_get_single(host: str, community: str, oid: str,
                            port: int = 161, timeout: int = 3) -> Optional[str]:
    """Single SNMP GET untuk satu OID penuh (misalnya sysDescr.0)."""
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
        for _, val in var_binds:
            v = str(val)
            if "NoSuchInstance" in v or "NoSuchObject" in v:
                return None
            return v.strip()
    except ImportError:
        return None
    except Exception as e:
        logger.warning(f"[SNMP] GET {host} {oid}: {e}")
        return None


# ── Interface Name Discovery ───────────────────────────────────────────────────

async def _get_ifnames(host: str, community: str, timeout: int = 3) -> Dict[int, str]:
    """
    {ifIndex: name} dengan 3-level fallback.
    Level 1: ifDescr — universal (RFC 2863), tersedia di semua device
    Level 2: ifName  — MikroTik short name (ether1, bridge1, etc.)
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
        syn = {idx: f"if{idx}" for idx in r}
        logger.warning(f"[SNMP DEBUG] {host}: synthetic OK → {len(syn)} ifaces")
        return syn

    logger.error(
        f"[SNMP DEBUG] {host}: SEMUA LEVEL GAGAL. "
        f"Cek: community string, SNMP enabled di IP Services, port 161/UDP."
    )
    return {}


# ── Single Poll Cycle ──────────────────────────────────────────────────────────

async def _single_poll(host: str, community: str,
                        timeout: int = 4) -> Optional[Dict]:
    """
    Satu siklus: ambil interface names + counters secara paralel.
    Return {iface_name: {in_octets, out_octets}} atau None jika gagal.
    """
    names = await _get_ifnames(host, community, timeout=timeout)
    if not names:
        return None

    # Coba 64-bit HC counters dulu (parallel)
    in64, out64 = await asyncio.gather(
        _snmp_get_indexed(host, community, OID_IF_HC_IN_OCTETS,
                          timeout=timeout, as_int=True),
        _snmp_get_indexed(host, community, OID_IF_HC_OUT_OCTETS,
                          timeout=timeout, as_int=True),
    )
    use64 = bool(in64)
    in_map, out_map = in64, out64

    if not use64:
        logger.debug(f"[SNMP] 64-bit HC kosong [{host}], fallback 32-bit...")
        in_map, out_map = await asyncio.gather(
            _snmp_get_indexed(host, community, OID_IF_IN_OCTETS,
                              timeout=timeout, as_int=True),
            _snmp_get_indexed(host, community, OID_IF_OUT_OCTETS,
                              timeout=timeout, as_int=True),
        )

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


# ── Device Info via SNMP ───────────────────────────────────────────────────────

async def get_device_snmp_info(host: str, community: str = "public",
                                port: int = 161, timeout: int = 4) -> Dict:
    """
    Ambil info device: sysDescr (versi RouterOS), sysName, uptime, jumlah iface.
    Gunakan untuk konfirmasi koneksi SNMP di UI.
    """
    sys_descr, sys_name, sys_uptime = await asyncio.gather(
        _snmp_get_single(host, community, OID_SYS_DESCR, port=port, timeout=timeout),
        _snmp_get_single(host, community, OID_SYS_NAME,  port=port, timeout=timeout),
        _snmp_get_single(host, community, OID_SYS_UPTIME, port=port, timeout=timeout),
    )

    info = {
        "snmp_reachable": bool(sys_descr),
        "sys_descr":      sys_descr or "",
        "sys_name":       sys_name  or "",
        "uptime_s":       0,
        "ros_version":    "",
        "interface_count": 0,
    }

    if sys_descr:
        m = re.search(r"(\d+\.\d+[\.\d]*)", sys_descr)
        if m:
            info["ros_version"] = m.group(1)

    if sys_uptime:
        try:
            info["uptime_s"] = int(sys_uptime) // 100
        except (ValueError, TypeError):
            pass

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
    """Delta 1-detik: T1 → sleep(1) → T2 → bps = (T2-T1)*8."""
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
    """Test koneksi SNMP via sysDescr.0."""
    result = await _snmp_get_single(host, community, OID_SYS_DESCR, timeout=timeout)
    return result is not None
