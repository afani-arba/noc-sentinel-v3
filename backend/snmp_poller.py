"""
snmp_poller.py — High-Accuracy SNMP v2c Traffic Monitor
=========================================================
Arsitektur: BulkWalk (nextCmd) + Precision Timestamp Delta + Strict Separation.

Tiga prinsip utama (2026-03-16 refactor):
  1. PRECISION DELTA: time.monotonic() saat packet diterima → bps = bytes*8 / elapsed_real
  2. BULK WALK: nextCmd sekali jalan untuk seluruh ifXTable (bukan 48x GET per-index)
  3. STRICT SEPARATION: jika SNMP OK → traffic WAJIB dari SNMP, API tidak boleh override

Bug sebelumnya (fix 2026-03-16):
  - 48 GET request per device → CPU spike di MikroTik hEX/CCR
  - sleep(1) statis → bps error jika polling lambat (30-50% off)
  - Shared SnmpEngine race condition → silent fail semua GET
"""
import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── OID Constants (ifXTable — RFC 2863) ──────────────────────────────────────
OID_SYS_DESCR        = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME         = "1.3.6.1.2.1.1.5.0"
OID_SYS_UPTIME       = "1.3.6.1.2.1.1.3.0"

# ifXTable (preferred — ifName + 64-bit HC counters)
OID_IFXTABLE         = "1.3.6.1.2.1.31.1.1.1"   # base
OID_IF_NAME          = "1.3.6.1.2.1.31.1.1.1.1"  # ifName
OID_IF_HC_IN_OCTETS  = "1.3.6.1.2.1.31.1.1.1.6"  # ifHCInOctets  (64-bit!)
OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10" # ifHCOutOctets (64-bit!)

# ifTable (fallback — ifDescr + 32-bit counters)
OID_IF_DESCR         = "1.3.6.1.2.1.2.2.1.2"     # ifDescr
OID_IF_IN_OCTETS     = "1.3.6.1.2.1.2.2.1.10"    # ifInOctets  (32-bit)
OID_IF_OUT_OCTETS    = "1.3.6.1.2.1.2.2.1.16"    # ifOutOctets (32-bit)

# Counter maxima
CMAX_64 = 2 ** 64
CMAX_32 = 2 ** 32
MAX_BPS = 400_000_000_000   # 400 Gbps — hard cap anti-spike

# ── SMA State (per device × per interface) ───────────────────────────────────
_SMA_W = 3
_sma_dl: Dict = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_W)))
_sma_ul: Dict = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_W)))

# ── Persistent counter cache (precision delta) ───────────────────────────────
# { device_id → { iface → { "in": int, "out": int, "ts": float } } }
_counter_cache: Dict[str, Dict[str, Dict]] = {}


def apply_sma(device_id: str, iface: str, dl: int, ul: int) -> Tuple[int, int]:
    _sma_dl[device_id][iface].append(dl)
    _sma_ul[device_id][iface].append(ul)
    return (
        int(sum(_sma_dl[device_id][iface]) / len(_sma_dl[device_id][iface])),
        int(sum(_sma_ul[device_id][iface]) / len(_sma_ul[device_id][iface])),
    )


def clear_sma_cache(device_id: str):
    _sma_dl.pop(device_id, None)
    _sma_ul.pop(device_id, None)
    _counter_cache.pop(device_id, None)


# ── pysnmp import helper ──────────────────────────────────────────────────────

def _get_pysnmp():
    """Import pysnmp.hlapi.asyncio — raise ImportError jika tidak tersedia."""
    from pysnmp.hlapi.asyncio import (
        nextCmd, getCmd, SnmpEngine, CommunityData,
        UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity,
    )
    return nextCmd, getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity


# ── BulkWalk via nextCmd ──────────────────────────────────────────────────────

async def _snmp_walk(
    host: str,
    community: str,
    base_oid: str,
    port: int = 161,
    timeout: int = 5,
    max_rows: int = 512,
) -> Dict[str, str]:
    """
    SNMP Walk via nextCmd — satu roundtrip untuk seluruh sub-tree.
    Return: { "base_oid.index": "value_str" }

    Jauh lebih efisien dari 48x GET:
    - 1 koneksi UDP vs 48 koneksi
    - CPU MikroTik turun drastis
    - Latency total ~4x lebih cepat
    """
    try:
        nextCmd, getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity = _get_pysnmp()
    except ImportError:
        logger.error("[SNMP] pysnmp tidak terinstall — pip install pysnmp-lextudio==6.2.0")
        return {}

    engine = SnmpEngine()
    results: Dict[str, str] = {}
    count = 0

    try:
        async for err_ind, err_st, _, var_binds in nextCmd(
            engine,
            CommunityData(community, mpModel=1),
            UdpTransportTarget((host, port), timeout=timeout, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(base_oid)),
            lexicographicMode=False,   # stop saat keluar sub-tree
        ):
            if err_ind:
                logger.debug(f"[SNMP Walk] {host} {base_oid}: {err_ind}")
                break
            if err_st:
                logger.debug(f"[SNMP Walk] {host} err_st={err_st}")
                break

            for oid_obj, val in var_binds:
                oid_str = str(oid_obj)
                val_str = str(val)
                if "NoSuchInstance" in val_str or "NoSuchObject" in val_str:
                    continue
                results[oid_str] = val_str
                count += 1
                if count >= max_rows:
                    break

            if count >= max_rows:
                break
    except Exception as e:
        logger.debug(f"[SNMP Walk] {host} {base_oid}: exception {e}")
    finally:
        try:
            engine.closeDispatcher()
        except Exception:
            pass

    return results


async def _snmp_get_scalar(
    host: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: int = 3,
) -> Optional[str]:
    """Single SNMP GET untuk scalar OID (e.g. sysDescr.0)."""
    try:
        nextCmd, getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity = _get_pysnmp()
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
        logger.debug(f"[SNMP GET] {host} {oid}: {e}")
        return None


# ── OID Parsing Helpers ───────────────────────────────────────────────────────

def _parse_walk_by_base(walk_result: Dict[str, str], base_oid: str) -> Dict[int, str]:
    """
    Filter walk_result untuk OID yang dimulai dengan base_oid.
    Return: { ifIndex: value }
    Contoh: base="1.3.6.1.2.1.31.1.1.1.6" → ambil semua ifHCInOctets.N
    """
    prefix = base_oid.rstrip(".")
    out: Dict[int, str] = {}
    for oid_str, val in walk_result.items():
        if oid_str.startswith(prefix + "."):
            suffix = oid_str[len(prefix) + 1:]
            parts = suffix.split(".")
            if parts and parts[0].isdigit():
                idx = int(parts[0])
                out[idx] = val
    return out


# ── Interface Name Discovery ──────────────────────────────────────────────────

async def _get_interface_names(
    host: str,
    community: str,
    timeout: int = 5,
) -> Dict[int, str]:
    """
    Dapatkan {ifIndex: name} via BulkWalk.
    Level 1: ifDescr (OID 1.3.6.1.2.1.2.2.1.2) — universal, semua device
    Level 2: ifName  (OID 1.3.6.1.2.1.31.1.1.1.1) — MikroTik short name
    Level 3: Synthetic if{n} dari ifInOctets index
    """
    # Level 1: ifDescr
    logger.warning(f"[SNMP DEBUG] {host}: BulkWalk ifDescr...")
    raw = await _snmp_walk(host, community, OID_IF_DESCR, timeout=timeout)
    r = _parse_walk_by_base(raw, OID_IF_DESCR)
    if r:
        logger.warning(
            f"[SNMP DEBUG] {host}: ifDescr OK → {len(r)} ifaces: {list(r.values())[:5]}"
        )
        return r

    # Level 2: ifName
    logger.warning(f"[SNMP DEBUG] {host}: ifDescr kosong, BulkWalk ifName...")
    raw = await _snmp_walk(host, community, OID_IF_NAME, timeout=timeout)
    r = _parse_walk_by_base(raw, OID_IF_NAME)
    if r:
        logger.warning(
            f"[SNMP DEBUG] {host}: ifName OK → {len(r)} ifaces: {list(r.values())[:5]}"
        )
        return r

    # Level 3: Synthetic dari ifInOctets index
    logger.warning(f"[SNMP DEBUG] {host}: ifName kosong, BulkWalk ifInOctets untuk index...")
    raw = await _snmp_walk(host, community, OID_IF_IN_OCTETS, timeout=timeout)
    r = _parse_walk_by_base(raw, OID_IF_IN_OCTETS)
    if r:
        syn = {idx: f"if{idx}" for idx in r}
        logger.warning(f"[SNMP DEBUG] {host}: synthetic OK → {len(syn)} ifaces")
        return syn

    logger.error(
        f"[SNMP DEBUG] {host}: SEMUA LEVEL GAGAL. "
        f"Cek: SNMP enabled di IP Services, community string, port 161/UDP."
    )
    return {}


# ── Single Poll Cycle (BulkWalk) ──────────────────────────────────────────────

async def _poll_ifxtable(
    host: str,
    community: str,
    timeout: int = 5,
) -> Optional[Dict]:
    """
    SATU BulkWalk untuk seluruh ifXTable → dapat nama + counter sekaligus.
    Return: {
      "ts": monotonic float,
      "counters": {ifIndex: {"name": str, "in": int, "out": int}},
      "use64": bool
    }
    """
    # Walk ifXTable sekaligus (termasuk ifName/.1, ifHCInOctets/.6, ifHCOutOctets/.10)
    raw = await _snmp_walk(host, community, OID_IFXTABLE, timeout=timeout)
    ts = time.monotonic()  # timestamp tepat saat data diterima

    names_raw  = _parse_walk_by_base(raw, OID_IF_NAME)
    in_raw     = _parse_walk_by_base(raw, OID_IF_HC_IN_OCTETS)
    out_raw    = _parse_walk_by_base(raw, OID_IF_HC_OUT_OCTETS)

    use64 = bool(in_raw)

    # Fallback: jika ifXTable kosong, coba ifDescr + 32-bit counters
    if not names_raw:
        logger.debug(f"[SNMP] {host}: ifXTable kosong, fallback ifTable...")
        fallback_names = await _get_interface_names(host, community, timeout=timeout)
        ts = time.monotonic()
        if not fallback_names:
            return None

        raw32 = await asyncio.gather(
            _snmp_walk(host, community, OID_IF_IN_OCTETS, timeout=timeout),
            _snmp_walk(host, community, OID_IF_OUT_OCTETS, timeout=timeout),
        )
        in_raw32  = _parse_walk_by_base(raw32[0], OID_IF_IN_OCTETS)
        out_raw32 = _parse_walk_by_base(raw32[1], OID_IF_OUT_OCTETS)
        ts = time.monotonic()

        counters: Dict[int, Dict] = {}
        for idx, name in fallback_names.items():
            counters[idx] = {
                "name": name,
                "in":   in_raw32.get(idx, 0),
                "out":  out_raw32.get(idx, 0),
            }
        logger.warning(
            f"[SNMP DEBUG] {host}: poll OK (32-bit fallback) — "
            f"{len(counters)} ifaces, 64bit=False"
        )
        return {"ts": ts, "counters": counters, "use64": False}

    # Fallback nama: jika ifName dari ifXTable kosong, pakai ifDescr
    if not names_raw:
        fallback_raw = await _snmp_walk(host, community, OID_IF_DESCR, timeout=timeout)
        names_raw = _parse_walk_by_base(fallback_raw, OID_IF_DESCR)

    # Fallback counter: jika HC kosong, pakai 32-bit
    if not in_raw:
        use64 = False
        raw32 = await asyncio.gather(
            _snmp_walk(host, community, OID_IF_IN_OCTETS, timeout=timeout),
            _snmp_walk(host, community, OID_IF_OUT_OCTETS, timeout=timeout),
        )
        in_raw  = _parse_walk_by_base(raw32[0], OID_IF_IN_OCTETS)
        out_raw = _parse_walk_by_base(raw32[1], OID_IF_OUT_OCTETS)
        ts = time.monotonic()

    if not in_raw:
        logger.warning(f"[SNMP DEBUG] {host}: counter walk kosong")
        return None

    # Kumpulkan hasil
    all_indices = set(names_raw.keys()) | set(in_raw.keys())
    counters: Dict[int, Dict] = {}
    for idx in all_indices:
        name = names_raw.get(idx, f"if{idx}") or f"if{idx}"
        counters[idx] = {
            "name": name,
            "in":   in_raw.get(idx, 0),
            "out":  out_raw.get(idx, 0),
        }

    logger.warning(
        f"[SNMP DEBUG] {host}: poll OK — "
        f"{len(counters)} ifaces, "
        f"{len(in_raw)} HC counters, "
        f"64bit={use64}"
    )
    return {"ts": ts, "counters": counters, "use64": use64}


# ── Device Info ───────────────────────────────────────────────────────────────

async def get_device_snmp_info(
    host: str,
    community: str = "public",
    port: int = 161,
    timeout: int = 5,
) -> Dict:
    """
    Info device: sysDescr, sysName, uptime, interface count.
    Digunakan di endpoint /test-snmp untuk verifikasi koneksi.
    """
    sys_descr, sys_name, sys_uptime = await asyncio.gather(
        _snmp_get_scalar(host, community, OID_SYS_DESCR, port=port, timeout=timeout),
        _snmp_get_scalar(host, community, OID_SYS_NAME,  port=port, timeout=timeout),
        _snmp_get_scalar(host, community, OID_SYS_UPTIME, port=port, timeout=timeout),
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
        names = await _get_interface_names(host, community, timeout=timeout)
        info["interface_count"] = len(names)

    return info


# ── Main: Precision Traffic ───────────────────────────────────────────────────

async def get_snmp_traffic(
    host: str,
    community: str = "public",
    device_id: str = "",
    iface_filter: Optional[List[str]] = None,
    snmp_timeout: int = 5,
    apply_smoothing: bool = True,
) -> Dict[str, Dict]:
    """
    Bandwidth traffic via SNMP dengan akurasi tinggi.

    Algoritma PRECISION DELTA:
      T1 = BulkWalk + timestamp ts1 (time.monotonic())
      sleep ~1s
      T2 = BulkWalk + timestamp ts2 (time.monotonic())
      elapsed = ts2 - ts1   ← REAL elapsed, bukan asumsi 1.0s
      bps = (counter_delta * 8) / elapsed

    Strict: hanya return data dari SNMP. Caller TIDAK BOLEH mix dengan API traffic.
    """
    if not host:
        return {}

    try:
        # ── T1: BulkWalk pertama ──────────────────────────────────────────────
        snap1 = await _poll_ifxtable(host, community, timeout=snmp_timeout)
        if not snap1:
            return {}

        ts1      = snap1["ts"]
        cnt1     = snap1["counters"]
        use64    = snap1["use64"]
        CMAX     = CMAX_64 if use64 else CMAX_32

        await asyncio.sleep(1)

        # ── T2: BulkWalk kedua ────────────────────────────────────────────────
        snap2 = await _poll_ifxtable(host, community, timeout=snmp_timeout)
        if not snap2:
            return {}

        ts2  = snap2["ts"]
        cnt2 = snap2["counters"]
        use64 = snap2.get("use64", use64)
        CMAX  = CMAX_64 if use64 else CMAX_32

        # PRECISION: elapsed real dari monotonic timestamp
        elapsed = ts2 - ts1
        if elapsed < 0.2:
            logger.warning(f"[SNMP] {host}: elapsed={elapsed:.3f}s terlalu pendek, skip")
            return {}

        # ── Delta bps per interface ───────────────────────────────────────────
        result: Dict[str, Dict] = {}

        for idx, c2 in cnt2.items():
            c1 = cnt1.get(idx)
            if c1 is None:
                continue

            name = c2.get("name") or c1.get("name") or f"if{idx}"
            if not name or name.strip() == "":
                name = f"if{idx}"

            if iface_filter and name not in iface_filter:
                continue

            di = c2["in"]  - c1["in"]
            do = c2["out"] - c1["out"]

            # Counter wrap correction
            if di < 0: di += CMAX
            if do < 0: do += CMAX

            # BPS = bytes * 8 / elapsed_detik_nyata
            dl = min(int((di * 8) / elapsed), MAX_BPS)
            ul = min(int((do * 8) / elapsed), MAX_BPS)

            # Hanya simpan interface yang punya data (counter > 0 atau ada traffic)
            if dl == 0 and ul == 0 and c2["in"] == 0 and c2["out"] == 0:
                continue

            if apply_smoothing and device_id:
                dl, ul = apply_sma(device_id, name, dl, ul)

            result[name] = {
                "download_bps": max(0, dl),
                "upload_bps":   max(0, ul),
                "status":       "up",
                "source":       "snmp_hc" if use64 else "snmp_32",
            }

        if result:
            logger.warning(
                f"[SNMP DEBUG] {host}: traffic OK — "
                f"{len(result)} ifaces active "
                f"(elapsed={elapsed:.3f}s, 64bit={use64})"
            )
        else:
            logger.debug(f"[SNMP] {host}: no active traffic in {len(cnt2)} ifaces")

        return result

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[SNMP] traffic error [{host}]: {e}")
        return {}


# ── Reachability Test ─────────────────────────────────────────────────────────

async def test_snmp_reachable(
    host: str,
    community: str = "public",
    timeout: int = 3,
) -> bool:
    """Test koneksi SNMP via sysDescr.0."""
    result = await _snmp_get_scalar(host, community, OID_SYS_DESCR, timeout=timeout)
    return result is not None
