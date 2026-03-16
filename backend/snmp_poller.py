"""
snmp_poller.py — Hybrid Monitoring SNMP Module
===============================================
Mengambil data traffic interface via SNMP v2c menggunakan 64-bit counters
(ifHCInOctets / ifHCOutOctets) agar akurat untuk perangkat CCR 10Gbps+.

Fitur:
  - Bulk Walk OID 64-bit (IF-MIB::ifHCInOctets & ifHCOutOctets)
  - Delta 1-detik: ambil T1, sleep 1s, ambil T2 → bps = (T2-T1)*8
  - Simple Moving Average (SMA window=3) untuk grafik yang mulus
  - asyncio.to_thread agar tidak blok event loop
  - Fallback graceful: jika SNMP gagal, return {} (caller handle fallback)
"""
import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── OID Constants ─────────────────────────────────────────────────────────────
OID_IF_NAME          = "1.3.6.1.2.1.31.1.1.1.1"   # ifName (string)
OID_IF_HC_IN_OCTETS  = "1.3.6.1.2.1.31.1.1.1.6"   # ifHCInOctets (64-bit)
OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10"  # ifHCOutOctets (64-bit)

# Fallback 32-bit (untuk device lama yang tidak support HC)
OID_IF_IN_OCTETS  = "1.3.6.1.2.1.2.2.1.10"  # ifInOctets (32-bit)
OID_IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16"  # ifOutOctets (32-bit)

# ── SMA (Simple Moving Average) State ─────────────────────────────────────────
# {device_id: {iface_name: deque([bps1, ..., bps5], maxlen=5)}}
# Window = 5 → mulus di grafik tanpa terlalu lag
_SMA_WINDOW = 5
_sma_dl_cache: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_WINDOW)))
_sma_ul_cache: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_WINDOW)))

# ── Track apakah device menggunakan 32-bit atau 64-bit OID ────────────────────
# {host: True/False} — True = 64-bit HC counter
_is_64bit: Dict[str, bool] = {}


def apply_sma(device_id: str, iface: str, dl_bps: int, ul_bps: int) -> tuple:
    """
    Terapkan Simple Moving Average pada nilai bandwidth.
    Return (smoothed_dl_bps, smoothed_ul_bps).
    Window = 3 polling cycles (~90 detik).
    """
    _sma_dl_cache[device_id][iface].append(dl_bps)
    _sma_ul_cache[device_id][iface].append(ul_bps)

    dl_smooth = int(sum(_sma_dl_cache[device_id][iface]) / len(_sma_dl_cache[device_id][iface]))
    ul_smooth = int(sum(_sma_ul_cache[device_id][iface]) / len(_sma_ul_cache[device_id][iface]))
    return dl_smooth, ul_smooth


def clear_sma_cache(device_id: str):
    """Hapus cache SMA untuk device yang sudah offline."""
    _sma_dl_cache.pop(device_id, None)
    _sma_ul_cache.pop(device_id, None)


# ── SNMP Bulk Walk (synchronous — dijalankan via asyncio.to_thread) ───────────

def _snmp_bulk_walk_sync(host: str, community: str, oid: str, timeout: int = 5, retries: int = 1) -> Dict[int, int]:
    """
    Synchronous SNMP bulk walk menggunakan pysnmp.
    Mengembalikan {ifIndex: value} untuk OID yang diberikan.
    Dijalankan di thread pool agar tidak blok event loop.
    """
    try:
        from snmp_compat import SnmpEngine, CommunityData, ContextData, ObjectType, ObjectIdentity, bulkCmd, PYSNMP_AVAILABLE, make_udp_transport
        if not PYSNMP_AVAILABLE:
            logger.error("pysnmp tidak terinstall! Jalankan: pip install pysnmp")
            return {}
    except ImportError:
        logger.error("snmp_compat tidak ditemukan")
        return {}

    result = {}
    try:
        engine = SnmpEngine()
        # make_udp_transport() handles pysnmp 7.x .create() dan pysnmp<7 langsung
        transport = make_udp_transport(host, 161, timeout, retries)
        community_data = CommunityData(community, mpModel=1)  # v2c

        for error_indication, error_status, error_index, var_binds in bulkCmd(
            engine,
            community_data,
            transport,
            ContextData(),
            0,   # nonRepeaters
            50,  # maxRepetitions=50 untuk BulkWalk yg lebih efisien (10x lebih cepat dari GetNext)
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,  # hanya ambil subtree OID tsb
        ):
            if error_indication:
                logger.debug(f"SNMP error [{host}] OID={oid}: {error_indication}")
                break
            if error_status:
                logger.debug(f"SNMP error status [{host}]: {error_status}")
                break

            for var_bind in var_binds:
                oid_full, val = var_bind
                # OID index = angka terakhir (ifIndex)
                oid_parts = str(oid_full).split(".")
                try:
                    idx = int(oid_parts[-1])
                    result[idx] = int(val)
                except (ValueError, TypeError):
                    pass

    except Exception as e:
        logger.debug(f"SNMP bulk walk gagal [{host}] OID={oid}: {e}")

    return result


def _snmp_get_ifnames_sync(host: str, community: str, timeout: int = 5) -> Dict[int, str]:
    """
    Ambil mapping ifIndex → ifName via SNMP.
    """
    try:
        from snmp_compat import SnmpEngine, CommunityData, ContextData, ObjectType, ObjectIdentity, bulkCmd, PYSNMP_AVAILABLE, make_udp_transport
        if not PYSNMP_AVAILABLE:
            return {}
    except ImportError:
        return {}

    result = {}
    try:
        engine = SnmpEngine()
        transport = make_udp_transport(host, 161, timeout, 1)
        community_data = CommunityData(community, mpModel=1)

        for error_indication, error_status, _, var_binds in bulkCmd(
            engine,
            community_data,
            transport,
            ContextData(),
            0, 50,
            ObjectType(ObjectIdentity(OID_IF_NAME)),
            lexicographicMode=False,
        ):
            if error_indication or error_status:
                break
            for var_bind in var_binds:
                oid_full, val = var_bind
                parts = str(oid_full).split(".")
                try:
                    idx = int(parts[-1])
                    result[idx] = str(val).strip()
                except (ValueError, TypeError):
                    pass
    except Exception as e:
        logger.debug(f"SNMP ifName gagal [{host}]: {e}")

    return result


def _snmp_single_walk_sync(host: str, community: str, timeout: int = 6) -> Optional[Dict[str, Dict]]:
    """
    Satu siklus SNMP walk: ambil ifName + ifHCIn + ifHCOut secara bersamaan.
    Return: {iface_name: {in_octets: int, out_octets: int, is_64bit: bool}} atau None jika gagal.
    Mencoba 64-bit HC counters dahulu, fallback ke 32-bit jika tidak ada.
    Track apakah device ini 64-bit atau 32-bit agar counter wrap dihitung benar.
    """
    names  = _snmp_get_ifnames_sync(host, community, timeout=timeout)
    if not names:
        logger.debug(f"SNMP gagal ambil ifName dari {host}")
        return None

    # Coba 64-bit HC counters
    in_map  = _snmp_bulk_walk_sync(host, community, OID_IF_HC_IN_OCTETS,  timeout=timeout)
    out_map = _snmp_bulk_walk_sync(host, community, OID_IF_HC_OUT_OCTETS, timeout=timeout)
    using_64bit = bool(in_map)

    # Jika HC counter kosong → fallback ke 32-bit
    if not in_map:
        logger.debug(f"SNMP 64-bit HC kosong [{host}], coba 32-bit...")
        in_map  = _snmp_bulk_walk_sync(host, community, OID_IF_IN_OCTETS,  timeout=timeout)
        out_map = _snmp_bulk_walk_sync(host, community, OID_IF_OUT_OCTETS, timeout=timeout)

    if not in_map:
        return None

    # Simpan info 64-bit untuk host ini (dipakai di wrap-around detection)
    _is_64bit[host] = using_64bit

    combined = {}
    for idx, name in names.items():
        combined[name] = {
            "in_octets":  in_map.get(idx, 0),
            "out_octets": out_map.get(idx, 0),
        }
    return combined


# ── Main SNMP Traffic Function ─────────────────────────────────────────────────

async def get_snmp_traffic(
    host: str,
    community: str = "public",
    device_id: str = "",
    iface_filter: Optional[list] = None,
    snmp_timeout: int = 5,
    apply_smoothing: bool = True,
) -> Dict[str, Dict]:
    """
    Ambil bandwidth real-time via SNMP v2c dengan metode delta 1-detik.

    Proses:
      1. SNMP walk T1 (ifHCInOctets + ifHCOutOctets)
      2. asyncio.sleep(1)
      3. SNMP walk T2
      4. bps = (T2 - T1) * 8
      5. Terapkan SMA(3) jika apply_smoothing=True

    Return:
      {iface_name: {download_bps, upload_bps, status, source}}
      Kosong ({}) jika SNMP tidak dapat dijangkau (caller handle fallback).
    """
    if not host:
        return {}

    try:
        # ── T1: ambil counter pertama ─────────────────────────────────────────
        t1_start = time.monotonic()
        t1 = await asyncio.to_thread(
            _snmp_single_walk_sync, host, community, snmp_timeout
        )
        if not t1:
            logger.debug(f"SNMP T1 gagal untuk {host}, skip")
            return {}

        # ── Sleep 1 detik untuk delta yang presisi ────────────────────────────
        await asyncio.sleep(1)

        # ── T2: ambil counter kedua ───────────────────────────────────────────
        t2 = await asyncio.to_thread(
            _snmp_single_walk_sync, host, community, snmp_timeout
        )
        if not t2:
            logger.debug(f"SNMP T2 gagal untuk {host}, skip")
            return {}

        elapsed = time.monotonic() - t1_start
        if elapsed < 0.5:
            elapsed = 1.0  # safety: hindari division by zero atau terlalu kecil

        # ── Hitung delta bps ──────────────────────────────────────────────────
        result = {}
        for iface_name, t2_data in t2.items():
            # Filter: hanya monitor interface yang ada di iface_filter
            if iface_filter and iface_name not in iface_filter:
                continue

            t1_data = t1.get(iface_name)
            if not t1_data:
                continue

            t2_in  = t2_data.get("in_octets", 0)
            t2_out = t2_data.get("out_octets", 0)
            t1_in  = t1_data.get("in_octets", 0)
            t1_out = t1_data.get("out_octets", 0)

            # Handle counter wrap-around
            # Gunakan MAX yang tepat: 64-bit untuk HC counters, 32-bit untuk fallback
            use_64bit = _is_64bit.get(host, True)
            COUNTER_MAX = (2 ** 64) if use_64bit else (2 ** 32)

            delta_in  = t2_in  - t1_in
            delta_out = t2_out - t1_out

            # Wrap-around: jika delta negatif, counter sudah wrap
            if delta_in < 0:
                delta_in = COUNTER_MAX + delta_in
            if delta_out < 0:
                delta_out = COUNTER_MAX + delta_out

            # Convert octets/s → bits/s
            dl_bps = int(delta_in  * 8)
            ul_bps = int(delta_out * 8)

            # Sanity check: nilai yang tidak masuk akal (>= 400Gbps) diabaikan
            MAX_SANE_BPS = 400_000_000_000
            if dl_bps > MAX_SANE_BPS:
                dl_bps = 0
            if ul_bps > MAX_SANE_BPS:
                ul_bps = 0

            # ── Terapkan SMA ─────────────────────────────────────────────────
            if apply_smoothing and device_id:
                dl_bps, ul_bps = apply_sma(device_id, iface_name, dl_bps, ul_bps)

            result[iface_name] = {
                "download_bps": dl_bps,
                "upload_bps":   ul_bps,
                "status":       "up",
                "source":       "snmp",
            }

        logger.debug(
            f"SNMP traffic OK [{host}]: {len(result)} ifaces, elapsed={elapsed:.2f}s"
        )
        return result

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"SNMP traffic error [{host}]: {e}")
        return {}


# ── SNMP Reachability Test ─────────────────────────────────────────────────────

async def test_snmp_reachable(host: str, community: str = "public", timeout: int = 3) -> bool:
    """
    Test apakah SNMP v2c dapat dijangkau di host.
    Cukup cek satu OID sederhana: sysDescr (1.3.6.1.2.1.1.1.0)
    Menggunakan snmp_compat bridge agar kompatibel dengan pysnmp 7.x.
    """
    def _test():
        try:
            from snmp_compat import SnmpEngine, CommunityData, ContextData, ObjectType, ObjectIdentity, getCmd, PYSNMP_AVAILABLE, make_udp_transport
            if not PYSNMP_AVAILABLE:
                return False
            engine = SnmpEngine()
            transport = make_udp_transport(host, 161, timeout, 0)
            for err_ind, err_st, _, vb in getCmd(
                engine,
                CommunityData(community, mpModel=1),
                transport,
                ContextData(),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")),
            ):
                if err_ind or err_st:
                    return False
                return True
            return False
        except Exception:
            return False

    try:
        return await asyncio.to_thread(_test)
    except Exception:
        return False
