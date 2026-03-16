"""
snmp_poller.py — SNMP v2c Traffic Monitor
==========================================
Uses pysnmp-lextudio >= 6.0.0 (from pysnmp.hlapi import ...)
nextCmd walk: reliable, stops cleanly at OID subtree boundary.

Fix 2026-03-16: simplified entire stack, direct import, no asyncio.run().
3-level fallback: ifDescr → ifName → synthetic.
"""
import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── OID Constants ─────────────────────────────────────────────────────────────
OID_IF_DESCR         = "1.3.6.1.2.1.2.2.1.2"    # ifDescr  (string)
OID_IF_NAME          = "1.3.6.1.2.1.31.1.1.1.1"  # ifName   (string, MikroTik)
OID_IF_HC_IN_OCTETS  = "1.3.6.1.2.1.31.1.1.1.6"  # ifHCInOctets  (64-bit)
OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10" # ifHCOutOctets (64-bit)
OID_IF_IN_OCTETS     = "1.3.6.1.2.1.2.2.1.10"    # ifInOctets    (32-bit)
OID_IF_OUT_OCTETS    = "1.3.6.1.2.1.2.2.1.16"    # ifOutOctets   (32-bit)

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


# ── SNMP Walk (sync, nextCmd) ──────────────────────────────────────────────────

def _walk(host: str, community: str, oid: str,
          timeout: int = 5, as_str: bool = True) -> dict:
    """
    Walk satu OID subtree via nextCmd (sync).
    Return {ifIndex: value} — value berupa str atau int tergantung as_str.

    nextCmd dipilih karena:
    - Lebih predictable: stop bersih saat keluar subtree
    - Tidak butuh maxRepetitions
    - Kompatibel semua versi pysnmp.hlapi
    """
    try:
        from pysnmp.hlapi import (
            SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity, nextCmd,
        )
    except ImportError:
        logger.error("[SNMP] pysnmp tidak terinstall — pip install 'pysnmp-lextudio>=6.0.0'")
        return {}

    result = {}
    base = oid.strip(".")

    try:
        engine    = SnmpEngine()
        community_ = CommunityData(community, mpModel=1)
        transport = UdpTransportTarget((host, 161), timeout, 1)
        context   = ContextData()

        for err_ind, err_st, _, var_binds in nextCmd(
            engine, community_, transport, context,
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            # EndOfMib atau timeout — stop walk
            if err_ind:
                logger.debug(f"[SNMP] nextCmd stop [{host}] OID={oid}: {err_ind}")
                break
            if err_st:
                logger.warning(f"[SNMP] nextCmd error [{host}] OID={oid}: {err_st}")
                break

            for oid_obj, val in var_binds:
                # Ekstrak ifIndex dari OID yang dikembalikan
                oid_s = str(oid_obj).strip()

                if "::" in oid_s:
                    # Format symbolic: "IF-MIB::ifDescr.5" → index=5
                    after = oid_s.split("::")[-1]   # "ifDescr.5"
                    tail  = after.rsplit(".", 1)     # ["ifDescr", "5"]
                    idx_s = tail[-1] if len(tail) > 1 else ""
                else:
                    # Format numeric: "1.3.6.1.2.1.2.2.1.2.5"
                    oid_c = oid_s.strip(".")
                    if not oid_c.startswith(base):
                        continue
                    suffix = oid_c[len(base):].lstrip(".")
                    idx_s  = suffix.split(".")[0] if suffix else ""

                if not idx_s:
                    continue
                try:
                    idx = int(idx_s)
                except ValueError:
                    continue

                try:
                    if as_str:
                        # prettyPrint handles OctetString correctly
                        v = val.prettyPrint() if hasattr(val, "prettyPrint") else str(val)
                        v = v.strip().strip("'\"")
                        if v and not v.startswith("0x"):
                            result[idx] = v
                        elif v.startswith("0x"):
                            # Hex bytes → decode as ASCII
                            try:
                                result[idx] = bytes.fromhex(v[2:]).decode("ascii", errors="ignore").strip()
                            except Exception:
                                result[idx] = v
                    else:
                        result[idx] = int(val)
                except (ValueError, TypeError):
                    pass

    except Exception as e:
        logger.warning(f"[SNMP] walk exception [{host}] OID={oid}: {type(e).__name__}: {e}")

    return result


# ── Interface Name Discovery ───────────────────────────────────────────────────

def _get_ifnames(host: str, community: str, timeout: int = 5) -> Dict[int, str]:
    """
    {ifIndex: interface_name} dengan 3-level fallback.
    Log realtime di WARNING level.
    """
    # Level 1: ifDescr — paling universal (RFC 2863, tersedia di semua device)
    logger.warning(f"[SNMP DEBUG] {host}: walk ifDescr...")
    r = _walk(host, community, OID_IF_DESCR, timeout=timeout, as_str=True)
    if r:
        logger.warning(f"[SNMP DEBUG] {host}: ifDescr OK → {len(r)} ifaces: {list(r.values())[:5]}")
        return r

    logger.warning(f"[SNMP DEBUG] {host}: ifDescr kosong, coba ifName...")

    # Level 2: ifName — nama pendek MikroTik (ether1, sfp1, bridge1)
    r = _walk(host, community, OID_IF_NAME, timeout=timeout, as_str=True)
    if r:
        logger.warning(f"[SNMP DEBUG] {host}: ifName OK → {len(r)} ifaces: {list(r.values())[:5]}")
        return r

    logger.warning(f"[SNMP DEBUG] {host}: ifName kosong, coba synthetic dari ifInOctets...")

    # Level 3: Synthetic — walk ifInOctets, ambil index saja → "if{n}"
    r = _walk(host, community, OID_IF_IN_OCTETS, timeout=timeout, as_str=False)
    if r:
        synth = {idx: f"if{idx}" for idx in r}
        logger.warning(f"[SNMP DEBUG] {host}: synthetic OK → {len(synth)} ifaces")
        return synth

    logger.error(
        f"[SNMP DEBUG] {host}: SEMUA LEVEL GAGAL. "
        f"Cek community string dan SNMP access-list di device."
    )
    return {}


# ── Single Poll Cycle ──────────────────────────────────────────────────────────

def _single_walk(host: str, community: str, timeout: int = 6) -> Optional[Dict[str, Dict]]:
    """
    Satu siklus: ambil interface names + counters.
    Return {iface_name: {in_octets, out_octets}} atau None jika gagal.
    """
    names = _get_ifnames(host, community, timeout=timeout)
    if not names:
        return None

    # 64-bit HC counters
    in_  = _walk(host, community, OID_IF_HC_IN_OCTETS,  timeout=timeout, as_str=False)
    out_ = _walk(host, community, OID_IF_HC_OUT_OCTETS, timeout=timeout, as_str=False)
    use64 = bool(in_)

    # Fallback 32-bit
    if not in_:
        logger.debug(f"[SNMP] 64-bit HC kosong [{host}], coba 32-bit...")
        in_  = _walk(host, community, OID_IF_IN_OCTETS,  timeout=timeout, as_str=False)
        out_ = _walk(host, community, OID_IF_OUT_OCTETS, timeout=timeout, as_str=False)

    if not in_:
        logger.warning(f"[SNMP DEBUG] {host}: counter walk juga kosong")
        return None

    _is_64bit[host] = use64
    logger.warning(
        f"[SNMP DEBUG] {host}: cycle OK — "
        f"{len(names)} ifaces, {len(in_)} counters, 64bit={use64}"
    )

    return {
        name: {"in_octets": in_.get(idx, 0), "out_octets": out_.get(idx, 0)}
        for idx, name in names.items()
    }


# ── Main: Bandwidth Real-Time ──────────────────────────────────────────────────

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
    """
    if not host:
        return {}
    try:
        t1 = await asyncio.to_thread(_single_walk, host, community, snmp_timeout)
        if not t1:
            return {}

        await asyncio.sleep(1)

        t2 = await asyncio.to_thread(_single_walk, host, community, snmp_timeout)
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
                "download_bps": dl, "upload_bps": ul,
                "status": "up", "source": "snmp",
            }

        logger.warning(f"[SNMP DEBUG] {host}: traffic OK — {len(result)} ifaces active")
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
            from pysnmp.hlapi import (
                SnmpEngine, CommunityData, UdpTransportTarget,
                ContextData, ObjectType, ObjectIdentity, getCmd,
            )
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
