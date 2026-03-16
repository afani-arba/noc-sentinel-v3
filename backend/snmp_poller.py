"""
snmp_poller.py — Hybrid Monitoring SNMP Module
===============================================
Traffic interface via SNMP v2c, 64-bit counters (ifHCInOctets/Out).

Fix 2026-03-16:
  - snmp_compat.py sekarang import UdpTransportTarget dari sync module
    (bukan async) → tidak ada type mismatch lagi → walk BERHASIL
  - Ganti bulkCmd → nextCmd untuk walk (lebih reliable, stop lebih bersih)
  - Exception log di WARNING (bukan DEBUG) agar kelihatan di produksi
  - 3-level fallback: ifDescr → ifName → synthetic dari ifInOctets
  - Delta 1-detik + SMA window=3
"""
import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── OID Constants ─────────────────────────────────────────────────────────────
OID_IF_DESCR         = "1.3.6.1.2.1.2.2.1.2"    # ifDescr  — paling universal
OID_IF_NAME          = "1.3.6.1.2.1.31.1.1.1.1"  # ifName   — nama pendek MikroTik
OID_IF_HC_IN_OCTETS  = "1.3.6.1.2.1.31.1.1.1.6"  # ifHCInOctets  (64-bit)
OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10" # ifHCOutOctets (64-bit)
OID_IF_IN_OCTETS     = "1.3.6.1.2.1.2.2.1.10"    # ifInOctets    (32-bit)
OID_IF_OUT_OCTETS    = "1.3.6.1.2.1.2.2.1.16"    # ifOutOctets   (32-bit)

# ── SMA State ─────────────────────────────────────────────────────────────────
_SMA_WINDOW = 3
_sma_dl: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_WINDOW)))
_sma_ul: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_WINDOW)))

# ── 64-bit tracking per host ──────────────────────────────────────────────────
_is_64bit: Dict[str, bool] = {}


def apply_sma(device_id: str, iface: str, dl_bps: int, ul_bps: int) -> tuple:
    _sma_dl[device_id][iface].append(dl_bps)
    _sma_ul[device_id][iface].append(ul_bps)
    dl = int(sum(_sma_dl[device_id][iface]) / len(_sma_dl[device_id][iface]))
    ul = int(sum(_sma_ul[device_id][iface]) / len(_sma_ul[device_id][iface]))
    return dl, ul


def clear_sma_cache(device_id: str):
    _sma_dl.pop(device_id, None)
    _sma_ul.pop(device_id, None)


# ── Core SNMP Walk (synchronous) ──────────────────────────────────────────────

def _snmp_walk(
    host: str, community: str, oid: str,
    timeout: int = 5, as_string: bool = True
) -> Dict[int, object]:
    """
    SNMP nextCmd walk untuk satu OID subtree.
    Menggunakan nextCmd (bukan bulkCmd) karena lebih reliable dan predictable.
    Return: {ifIndex: value} atau {} jika gagal.

    KRITIS: snmp_compat.py sekarang import UdpTransportTarget dari
    pysnmp.hlapi.v3arch.sync (SYNC class) — tidak perlu asyncio.run().
    Transport ini compatible dengan nextCmd dari modul yang sama.
    """
    try:
        from snmp_compat import (
            SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity, nextCmd, PYSNMP_AVAILABLE
        )
        if not PYSNMP_AVAILABLE:
            return {}
    except ImportError:
        return {}

    result: Dict[int, object] = {}
    base = oid.strip(".")

    try:
        engine     = SnmpEngine()
        community_ = CommunityData(community, mpModel=1)
        transport  = UdpTransportTarget((host, 161), timeout, 1)
        context    = ContextData()

        for err_ind, err_st, _, var_binds in nextCmd(
            engine, community_, transport, context,
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            if err_ind:
                # Bisa EndOfMib (normal) atau request timeout
                logger.debug(f"[SNMP] nextCmd signal [{host}] OID={oid}: {err_ind}")
                break
            if err_st:
                logger.warning(f"[SNMP] nextCmd error [{host}] OID={oid}: {err_st}")
                break

            for oid_obj, val in var_binds:
                # Ekstrak ifIndex dari OID akhir
                oid_str = str(oid_obj).strip()

                # Handle symbolic format: "IF-MIB::ifDescr.5" → 5
                if "::" in oid_str:
                    after = oid_str.split("::")[-1]   # "ifDescr.5"
                    parts = after.split(".")
                else:
                    # Numeric format: "1.3.6.1.2.1.2.2.1.2.5"
                    oid_clean = oid_str.strip(".")
                    if not oid_clean.startswith(base):
                        continue
                    suffix = oid_clean[len(base):].lstrip(".")
                    parts = suffix.split(".") if suffix else []

                if not parts:
                    continue
                try:
                    idx = int(parts[-1])
                except ValueError:
                    continue

                try:
                    if as_string:
                        # Handle OctetString: bisa berupa bytes representation
                        v = val.prettyPrint() if hasattr(val, "prettyPrint") else str(val)
                        v = v.strip().strip("'\"")
                        if v:
                            result[idx] = v
                    else:
                        result[idx] = int(val)
                except (ValueError, TypeError):
                    pass

    except Exception as e:
        logger.warning(f"[SNMP] walk exception [{host}] OID={oid}: {type(e).__name__}: {e}")

    return result


# ── Interface Name Discovery ───────────────────────────────────────────────────

def _snmp_get_ifnames(host: str, community: str, timeout: int = 5) -> Dict[int, str]:
    """
    Ambil {ifIndex: name} via SNMP, 3-level fallback:
      1. ifDescr (1.3.6.1.2.1.2.2.1.2)      — paling universal
      2. ifName  (1.3.6.1.2.1.31.1.1.1.1)   — MikroTik short name
      3. Synthetic "if{n}" dari ifInOctets   — last resort

    Log [SNMP DEBUG] di WARNING untuk troubleshoot realtime.
    """
    # Level 1: ifDescr
    logger.warning(f"[SNMP DEBUG] {host}: walk ifDescr ({OID_IF_DESCR})...")
    result = _snmp_walk(host, community, OID_IF_DESCR, timeout=timeout, as_string=True)
    if result:
        logger.warning(f"[SNMP DEBUG] {host}: ifDescr OK → {len(result)} ifaces: {list(result.values())[:6]}")
        return result

    logger.warning(f"[SNMP DEBUG] {host}: ifDescr kosong, coba ifName ({OID_IF_NAME})...")

    # Level 2: ifName
    result = _snmp_walk(host, community, OID_IF_NAME, timeout=timeout, as_string=True)
    if result:
        logger.warning(f"[SNMP DEBUG] {host}: ifName OK → {len(result)} ifaces: {list(result.values())[:6]}")
        return result

    logger.warning(f"[SNMP DEBUG] {host}: ifName kosong, coba synthetic dari ifInOctets...")

    # Level 3: Synthetic dari ifInOctets (numeric) — ambil index saja
    octets = _snmp_walk(host, community, OID_IF_IN_OCTETS, timeout=timeout, as_string=False)
    if octets:
        synthetic = {idx: f"if{idx}" for idx in octets}
        logger.warning(f"[SNMP DEBUG] {host}: synthetic OK → {len(synthetic)} ifaces: {list(synthetic.values())[:6]}")
        return synthetic

    logger.error(
        f"[SNMP DEBUG] {host}: SEMUA LEVEL GAGAL (0 interfaces). "
        f"Cek: community string, SNMP access-list di device, dan port 161/udp."
    )
    return {}


# ── Numeric Counter Walk ───────────────────────────────────────────────────────

def _snmp_walk_int(host: str, community: str, oid: str, timeout: int = 5) -> Dict[int, int]:
    return _snmp_walk(host, community, oid, timeout=timeout, as_string=False)


# ── Single Poll Cycle ──────────────────────────────────────────────────────────

def _snmp_single_walk_sync(host: str, community: str, timeout: int = 6) -> Optional[Dict[str, Dict]]:
    """
    Satu siklus: ambil ifNames + counter T1.
    Return {iface_name: {in_octets, out_octets}} atau None jika gagal.
    """
    names = _snmp_get_ifnames(host, community, timeout=timeout)
    if not names:
        return None

    # Coba 64-bit HC counters
    in_map  = _snmp_walk_int(host, community, OID_IF_HC_IN_OCTETS,  timeout=timeout)
    out_map = _snmp_walk_int(host, community, OID_IF_HC_OUT_OCTETS, timeout=timeout)
    using64 = bool(in_map)

    # Fallback ke 32-bit
    if not in_map:
        logger.debug(f"[SNMP] 64-bit HC kosong [{host}], coba 32-bit...")
        in_map  = _snmp_walk_int(host, community, OID_IF_IN_OCTETS,  timeout=timeout)
        out_map = _snmp_walk_int(host, community, OID_IF_OUT_OCTETS, timeout=timeout)

    if not in_map:
        logger.warning(f"[SNMP DEBUG] {host}: counter OID juga kosong")
        return None

    _is_64bit[host] = using64
    logger.warning(
        f"[SNMP DEBUG] {host}: T-walk OK — "
        f"{len(names)} ifaces, {len(in_map)} counters, 64bit={using64}"
    )

    return {
        name: {"in_octets": in_map.get(idx, 0), "out_octets": out_map.get(idx, 0)}
        for idx, name in names.items()
    }


# ── Main: Ambil Bandwidth Real-Time ───────────────────────────────────────────

async def get_snmp_traffic(
    host: str,
    community: str = "public",
    device_id: str = "",
    iface_filter: Optional[list] = None,
    snmp_timeout: int = 5,
    apply_smoothing: bool = True,
) -> Dict[str, Dict]:
    """
    Delta 1-detik: T1 → sleep(1) → T2 → bps = (T2-T1)*8.
    Return {iface_name: {download_bps, upload_bps, status, source}}.
    """
    if not host:
        return {}
    try:
        t1_start = time.monotonic()
        t1 = await asyncio.to_thread(_snmp_single_walk_sync, host, community, snmp_timeout)
        if not t1:
            return {}

        await asyncio.sleep(1)

        t2 = await asyncio.to_thread(_snmp_single_walk_sync, host, community, snmp_timeout)
        if not t2:
            return {}

        elapsed = max(time.monotonic() - t1_start, 0.5)
        COUNTER_MAX = (2 ** 64) if _is_64bit.get(host, True) else (2 ** 32)
        MAX_SANE = 400_000_000_000

        result = {}
        for iface, t2d in t2.items():
            if iface_filter and iface not in iface_filter:
                continue
            t1d = t1.get(iface)
            if not t1d:
                continue

            di = t2d["in_octets"]  - t1d["in_octets"]
            do = t2d["out_octets"] - t1d["out_octets"]
            if di < 0: di += COUNTER_MAX
            if do < 0: do += COUNTER_MAX

            dl = min(int(di * 8), MAX_SANE)
            ul = min(int(do * 8), MAX_SANE)

            if apply_smoothing and device_id:
                dl, ul = apply_sma(device_id, iface, dl, ul)

            result[iface] = {
                "download_bps": dl,
                "upload_bps":   ul,
                "status":       "up",
                "source":       "snmp",
            }

        logger.warning(f"[SNMP DEBUG] {host}: traffic OK — {len(result)} ifaces, elapsed={elapsed:.1f}s")
        return result

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[SNMP] traffic error [{host}]: {e}")
        return {}


# ── Reachability Test ─────────────────────────────────────────────────────────

async def test_snmp_reachable(host: str, community: str = "public", timeout: int = 3) -> bool:
    def _test():
        try:
            from snmp_compat import (
                SnmpEngine, CommunityData, UdpTransportTarget,
                ContextData, ObjectType, ObjectIdentity, getCmd, PYSNMP_AVAILABLE
            )
            if not PYSNMP_AVAILABLE:
                return False
            for err_ind, err_st, _, _ in getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),
                UdpTransportTarget((host, 161), timeout, 0),
                ContextData(),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")),
            ):
                return not (err_ind or err_st)
            return False
        except Exception:
            return False
    try:
        return await asyncio.to_thread(_test)
    except Exception:
        return False
