"""
snmp_poller.py — Hybrid Monitoring SNMP Module
===============================================
Mengambil data traffic interface via SNMP v2c menggunakan 64-bit counters
(ifHCInOctets / ifHCOutOctets) agar akurat untuk perangkat CCR 10Gbps+.

Fitur:
  - Bulk Walk OID 64-bit (IF-MIB::ifHCInOctets & ifHCOutOctets)
  - Delta 1-detik: ambil T1, sleep 1s, ambil T2 → bps = (T2-T1)*8
  - Simple Moving Average (SMA window=5) untuk grafik yang mulus
  - asyncio.to_thread agar tidak blok event loop
  - Fallback graceful: jika SNMP gagal, return {} (caller handle fallback)

Fix (2026-03-16):
  - _snmp_walk_oid_robust: transport baru tiap percobaan, toleran symbolic OID
  - _snmp_get_ifnames_sync: 4-level fallback + debug log per step
  - Retry dengan ifIndex jika semua OID string gagal
  - [SNMP DEBUG] log di setiap langkah untuk troubleshoot REALTIME
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
OID_IF_HC_IN_OCTETS  = "1.3.6.1.2.1.31.1.1.1.6"  # ifHCInOctets (64-bit)
OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10" # ifHCOutOctets (64-bit)
OID_IF_TYPE          = "1.3.6.1.2.1.2.2.1.3"     # ifType (untuk ifIndex walk)

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
    Window = 5 polling cycles (~150 detik).
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


# ── SNMP Import Helper ─────────────────────────────────────────────────────────

def _get_snmp_tools():
    """
    Import SNMP tools via snmp_compat bridge.
    Return dict dengan semua tool atau None jika pysnmp tidak tersedia.
    """
    try:
        from snmp_compat import (
            SnmpEngine, CommunityData, ContextData,
            ObjectType, ObjectIdentity, bulkCmd, getCmd,
            PYSNMP_AVAILABLE, make_udp_transport
        )
        if not PYSNMP_AVAILABLE:
            return None
        return {
            "SnmpEngine": SnmpEngine,
            "CommunityData": CommunityData,
            "ContextData": ContextData,
            "ObjectType": ObjectType,
            "ObjectIdentity": ObjectIdentity,
            "bulkCmd": bulkCmd,
            "getCmd": getCmd,
            "make_udp_transport": make_udp_transport,
        }
    except ImportError:
        return None


def _extract_index_from_oid(oid_full_str: str, base_oid: str) -> Optional[int]:
    """
    Ekstrak ifIndex dari OID response pysnmp.

    Handles 2 format yang pysnmp kembalikan:
      1. Numeric: "1.3.6.1.2.1.2.2.1.2.5" → index = 5
      2. Symbolic: "IF-MIB::ifDescr.5"     → index = 5

    Return int index atau None jika tidak bisa diparse.
    """
    s = str(oid_full_str).strip()

    # Format symbolic: "IF-MIB::ifDescr.5" → ambil setelah titik terakhir
    if "::" in s:
        after_colon = s.split("::")[-1]
        # Bisa juga "ifDescr.5" atau "ifName.1"
        parts = after_colon.split(".")
        if parts:
            try:
                return int(parts[-1])
            except ValueError:
                pass
        return None

    # Format numeric: "1.3.6.1.2.1.2.2.1.2.5"
    # Verifikasi bahwa OID ini memang subtree dari base_oid
    base_clean = base_oid.strip(".")
    oid_clean  = s.strip(".")

    if oid_clean.startswith(base_clean):
        suffix = oid_clean[len(base_clean):].lstrip(".")
        if suffix:
            try:
                return int(suffix.split(".")[0])
            except ValueError:
                pass
    else:
        # Fallback: ambil saja angka terakhir
        parts = oid_clean.split(".")
        try:
            return int(parts[-1])
        except ValueError:
            pass

    return None


# ── SNMP Walk Robust ───────────────────────────────────────────────────────────

def _snmp_walk_oid_robust(
    host: str,
    community: str,
    oid: str,
    timeout: int = 5,
    retries: int = 1,
    max_repetitions: int = 50,
    return_string: bool = True,
) -> Dict[int, object]:
    """
    SNMP bulk walk yang robust untuk pysnmp 7.x dan lama.

    PENTING: Buat transport baru setiap kali fungsi ini dipanggil.
    pysnmp 7.x UdpTransportTarget TIDAK bisa di-reuse di antara bulkCmd calls.

    Params:
      return_string: True  → return {idx: str(val)}
                     False → return {idx: int(val)}
    """
    tools = _get_snmp_tools()
    if tools is None:
        return {}

    result = {}
    try:
        engine        = tools["SnmpEngine"]()
        community_obj = tools["CommunityData"](community, mpModel=1)
        # Buat transport BARU tiap panggilan (fix pysnmp 7.x transport reuse bug)
        transport     = tools["make_udp_transport"](host, 161, timeout, retries)

        for err_ind, err_st, _, var_binds in tools["bulkCmd"](
            engine,
            community_obj,
            transport,
            tools["ContextData"](),
            0,                  # nonRepeaters
            max_repetitions,
            tools["ObjectType"](tools["ObjectIdentity"](oid)),
            lexicographicMode=False,
        ):
            if err_ind:
                logger.debug(f"[SNMP DEBUG] bulkCmd error [{host}] OID={oid}: {err_ind}")
                break
            if err_st:
                logger.debug(f"[SNMP DEBUG] bulkCmd status [{host}] OID={oid}: {err_st}")
                break

            for var_bind in var_binds:
                oid_full, val = var_bind
                idx = _extract_index_from_oid(str(oid_full), oid)
                if idx is None:
                    continue
                try:
                    if return_string:
                        v = str(val).strip()
                        if v and v not in ("", "''", "b''"):
                            result[idx] = v
                    else:
                        result[idx] = int(val)
                except (ValueError, TypeError):
                    pass

    except Exception as e:
        logger.debug(f"[SNMP DEBUG] walk exception [{host}] OID={oid}: {e}")

    return result


# ── Interface Name Discovery dengan 4-Level Fallback ─────────────────────────

def _snmp_get_ifnames_sync(host: str, community: str, timeout: int = 5) -> Dict[int, str]:
    """
    Ambil mapping ifIndex → interface_name via SNMP dengan 4-level fallback:

      Level 1: ifDescr (1.3.6.1.2.1.2.2.1.2)   — paling universal, didukung semua device
      Level 2: ifName  (1.3.6.1.2.1.31.1.1.1.1) — nama pendek MikroTik (ether1, bridge1)
      Level 3: ifType  (1.3.6.1.2.1.2.2.1.3)    — ambil index saja → nama "if{n}_type{t}"
      Level 4: ifInOctets walk                   — ambil index saja → nama "if{n}"

    Debug log [SNMP DEBUG] tampil di terminal backend untuk troubleshoot realtime.

    FIX 2026-03-16:
      - Transport baru tiap level (tidak reuse — pysnmp 7.x bug)
      - Toleran terhadap symbolic OID format "IF-MIB::ifDescr.N"
      - Log warning jika semua level gagal
    """
    tools = _get_snmp_tools()
    if tools is None:
        logger.warning(f"[SNMP DEBUG] {host}: pysnmp tidak tersedia")
        return {}

    # ── Level 1: ifDescr — paling universal ──────────────────────────────────
    logger.warning(f"[SNMP DEBUG] {host}: mencoba ifDescr ({OID_IF_DESCR})...")
    result = _snmp_walk_oid_robust(host, community, OID_IF_DESCR, timeout=timeout, return_string=True)
    if result:
        logger.warning(f"[SNMP DEBUG] {host}: ifDescr OK → {len(result)} interfaces: {list(result.values())[:8]}")
        return result

    logger.warning(f"[SNMP DEBUG] {host}: ifDescr kosong (0), coba ifName...")

    # ── Level 2: ifName — nama pendek MikroTik ───────────────────────────────
    result = _snmp_walk_oid_robust(host, community, OID_IF_NAME, timeout=timeout, return_string=True)
    if result:
        logger.warning(f"[SNMP DEBUG] {host}: ifName OK → {len(result)} interfaces: {list(result.values())[:8]}")
        return result

    logger.warning(f"[SNMP DEBUG] {host}: ifName kosong (0), coba ifType untuk ambil index...")

    # ── Level 3: ifType walk — ambil index saja, buat nama "ifN_Ttype" ───────
    type_map = _snmp_walk_oid_robust(host, community, OID_IF_TYPE, timeout=timeout, return_string=False)
    if type_map:
        # Gunakan type untuk membuat nama lebih informatif
        TYPE_NAMES = {
            6: "ether", 53: "bridge", 161: "ieee8023adLag",
            24: "softwareLoopback", 131: "tunnel", 23: "ppp",
        }
        iface_names = {}
        for idx, itype in type_map.items():
            type_str = TYPE_NAMES.get(int(itype), "if")
            iface_names[idx] = f"{type_str}{idx}"
        logger.warning(
            f"[SNMP DEBUG] {host}: ifType fallback → {len(iface_names)} interfaces: "
            f"{list(iface_names.values())[:8]}"
        )
        return iface_names

    logger.warning(f"[SNMP DEBUG] {host}: ifType kosong (0), coba ifInOctets untuk index...")

    # ── Level 4: ifInOctets walk — ambil index saja, buat nama "ifN" ─────────
    octets_map = _snmp_walk_oid_robust(host, community, OID_IF_IN_OCTETS, timeout=timeout, return_string=False)
    if octets_map:
        synthetic = {idx: f"if{idx}" for idx in octets_map}
        logger.warning(
            f"[SNMP DEBUG] {host}: synthetic dari ifInOctets → {len(synthetic)} interfaces: "
            f"{list(synthetic.values())[:8]}"
        )
        return synthetic

    logger.error(
        f"[SNMP DEBUG] {host}: SEMUA LEVEL GAGAL (0 interfaces). "
        f"SNMP mungkin tidak ada izin atau komunitas salah."
    )
    return {}


# ── SNMP Bulk Walk Numerik ─────────────────────────────────────────────────────

def _snmp_bulk_walk_sync(host: str, community: str, oid: str, timeout: int = 5, retries: int = 1) -> Dict[int, int]:
    """
    SNMP bulk walk untuk nilai numerik (counter bytes).
    Mengembalikan {ifIndex: value_int}.
    """
    return _snmp_walk_oid_robust(host, community, oid, timeout=timeout, retries=retries, return_string=False)


# ── Single Walk Cycle ──────────────────────────────────────────────────────────

def _snmp_single_walk_sync(host: str, community: str, timeout: int = 6) -> Optional[Dict[str, Dict]]:
    """
    Satu siklus SNMP walk: ambil ifName + ifHCIn + ifHCOut secara bersamaan.
    Return: {iface_name: {in_octets: int, out_octets: int}} atau None jika gagal.
    Mencoba 64-bit HC counters dahulu, fallback ke 32-bit jika tidak ada.
    Track apakah device ini 64-bit atau 32-bit agar counter wrap dihitung benar.
    """
    names = _snmp_get_ifnames_sync(host, community, timeout=timeout)
    if not names:
        logger.debug(f"SNMP gagal ambil interface dari {host}")
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
        logger.warning(f"[SNMP DEBUG] {host}: counter OID juga kosong — device tidak support SNMP traffic?")
        return None

    # Simpan info 64-bit untuk host ini (dipakai di wrap-around detection)
    _is_64bit[host] = using_64bit

    logger.warning(
        f"[SNMP DEBUG] {host}: walk OK — "
        f"{len(names)} ifaces, {len(in_map)} in_counters, 64bit={using_64bit}"
    )

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
      5. Terapkan SMA(5) jika apply_smoothing=True

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

        logger.warning(
            f"[SNMP DEBUG] {host}: traffic delta OK — "
            f"{len(result)} ifaces active, elapsed={elapsed:.2f}s"
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
            from snmp_compat import (
                SnmpEngine, CommunityData, ContextData,
                ObjectType, ObjectIdentity, getCmd,
                PYSNMP_AVAILABLE, make_udp_transport
            )
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
