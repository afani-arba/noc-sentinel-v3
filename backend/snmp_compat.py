"""
snmp_compat.py — Compatibility bridge for pysnmp API changes
============================================================
Mendukung:
  pysnmp >= 7.x (paket 'pysnmp'):
      - Sync API ada di pysnmp.hlapi.v3arch.sync
      - UdpTransportTarget dari sync module = sync class (no asyncio needed!)
      - bulkCmd / getCmd / nextCmd dari sync module = sync generators ✓

  pysnmp-lextudio / pysnmp < 7 (lama):
      - pysnmp.hlapi langsung: sync class, sync generators ✓

FIX KRITIS 2026-03-16:
  Bug sebelumnya: UdpTransportTarget diambil dari pysnmp.hlapi.v3arch (ASYNC!)
  tapi bulkCmd diambil dari pysnmp.hlapi.v3arch.sync (SYNC).
  Akibat: type mismatch → walk silent fail → 0 interfaces.

  Fix: Ambil SEMUA symbols dari satu modul yang konsisten (sync).
  UdpTransportTarget dari sync module = sync class, no asyncio.run() needed.
"""
import logging

logger = logging.getLogger(__name__)

PYSNMP_AVAILABLE = False
PYSNMP_VERSION   = 0

SnmpEngine = CommunityData = UdpTransportTarget = ContextData = None
ObjectType = ObjectIdentity = bulkCmd = getCmd = nextCmd = Integer32 = None

# ── Attempt 1: pysnmp 7.x — import SEMUA dari sync module ────────────────────
# KRITIS: UdpTransportTarget harus dari modul SAMA dengan bulkCmd/getCmd
# Jika dari async module, transport incompatible dengan sync commands!
try:
    from pysnmp.hlapi.v3arch.sync import (   # type: ignore[import]
        SnmpEngine,
        CommunityData,
        UdpTransportTarget,   # ← SYNC version, no asyncio.run() needed
        ContextData,
        ObjectType,
        ObjectIdentity,
        bulkCmd,
        getCmd,
        nextCmd,
    )
    try:
        from pysnmp.proto.rfc1902 import Integer32  # type: ignore[import]
    except ImportError:
        Integer32 = None

    PYSNMP_AVAILABLE = True
    PYSNMP_VERSION   = 7
    logger.warning("snmp_compat: pysnmp 7.x SYNC loaded OK (v3arch.sync)")

except ImportError:
    # ── Attempt 2: pysnmp-lextudio / pysnmp < 7 ─────────────────────────────
    try:
        from pysnmp.hlapi import (   # type: ignore[import]
            SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity, bulkCmd, getCmd, nextCmd, Integer32,
        )
        PYSNMP_AVAILABLE = True
        PYSNMP_VERSION   = 6
        logger.warning("snmp_compat: pysnmp-lextudio (v6) loaded OK")
    except ImportError:
        logger.warning("snmp_compat: pysnmp TIDAK TERINSTALL — SNMP nonaktif")


def make_udp_transport(host: str, port: int = 161, timeout: int = 5, retries: int = 1):
    """
    Buat UdpTransportTarget yang kompatibel dengan pysnmp 7.x sync dan lama.

    Dengan fix baru ini (import dari hlapi.v3arch.sync), UdpTransportTarget
    adalah SYNC class — langsung konstruktor, TIDAK perlu asyncio.run() lagi!
    Sama persis dengan pysnmp < 7 (lextudio).
    """
    if not PYSNMP_AVAILABLE or UdpTransportTarget is None:
        raise RuntimeError("pysnmp tidak terinstall")

    # Coba positional args dulu, fallback ke keyword
    try:
        return UdpTransportTarget((host, port), timeout, retries)
    except Exception:
        return UdpTransportTarget((host, port), timeout=timeout, retries=retries)
