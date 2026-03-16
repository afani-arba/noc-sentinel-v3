"""
snmp_compat.py — Compatibility bridge for pysnmp API changes
============================================================
Mendukung:
  pysnmp >= 7.x (paket 'pysnmp'):
      - UdpTransportTarget sekarang async class, harus pakai .create()
      - SnmpEngine, CommunityData dll di pysnmp.hlapi.v3arch
      - bulkCmd / getCmd sudah async generator
  pysnmp-lextudio / pysnmp < 7 (lama):
      - UdpTransportTarget langsung bisa: UdpTransportTarget((host,port), t, r)
      - bulkCmd / getCmd adalah sync generator

Gunakan fungsi make_udp_transport() dari modul ini untuk membuat transport
yang kompatibel dengan kedua versi tanpa perlu tahu versi aktifnya.
"""
import logging
import asyncio

logger = logging.getLogger(__name__)

PYSNMP_AVAILABLE = False
PYSNMP_VERSION   = 0

SnmpEngine = CommunityData = UdpTransportTarget = ContextData = None
ObjectType = ObjectIdentity = bulkCmd = getCmd = nextCmd = Integer32 = None

# ── Attempt 1: pysnmp 7.x ────────────────────────────────────────────────────
try:
    from pysnmp.hlapi.v3arch import (   # type: ignore[import]
        SnmpEngine,
        CommunityData,
        UdpTransportTarget,
        ContextData,
        ObjectType,
        ObjectIdentity,
    )
    # Coba sync commands dulu, fallback ke hlapi
    _cmd_loaded = False
    try:
        from pysnmp.hlapi.v3arch.sync import bulkCmd, getCmd, nextCmd  # type: ignore[import]
        _cmd_loaded = True
    except ImportError:
        pass
    if not _cmd_loaded:
        try:
            from pysnmp.hlapi import bulkCmd, getCmd, nextCmd  # type: ignore[import]
            _cmd_loaded = True
        except ImportError:
            pass
    if not _cmd_loaded:
        def bulkCmd(*a, **k): return iter([])   # type: ignore
        def getCmd(*a, **k):  return iter([])   # type: ignore
        def nextCmd(*a, **k): return iter([])   # type: ignore

    try:
        from pysnmp.proto.rfc1902 import Integer32  # type: ignore[import]
    except ImportError:
        Integer32 = None

    PYSNMP_AVAILABLE = True
    PYSNMP_VERSION   = 7
    logger.debug("snmp_compat: pysnmp 7.x loaded")

except ImportError:
    # ── Attempt 2: pysnmp-lextudio / pysnmp < 7 ─────────────────────────────
    try:
        from pysnmp.hlapi import (   # type: ignore[import]
            SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity, bulkCmd, getCmd, nextCmd, Integer32,
        )
        PYSNMP_AVAILABLE = True
        PYSNMP_VERSION   = 6
        logger.debug("snmp_compat: pysnmp-lextudio (v6) loaded")
    except ImportError:
        logger.warning("snmp_compat: pysnmp tidak terinstall")


def make_udp_transport(host: str, port: int = 161, timeout: int = 5, retries: int = 1):
    """
    Buat UdpTransportTarget yang kompatibel dengan pysnmp 7.x maupun lama.

    pysnmp 7.x: UdpTransportTarget adalah async class → pakai asyncio.run(.create())
                Aman dipanggil dari thread (via asyncio.to_thread) karena
                thread tidak punya event loop aktif.
    pysnmp < 7: UdpTransportTarget adalah sync class → langsung konstruktor.
    """
    if not PYSNMP_AVAILABLE or UdpTransportTarget is None:
        raise RuntimeError("pysnmp tidak terinstall")

    if PYSNMP_VERSION >= 7:
        # pysnmp 7.x: .create() adalah async classmethod
        try:
            return asyncio.run(
                UdpTransportTarget.create((host, port), timeout, retries)
            )
        except Exception:
            # Fallback: coba juga dengan keyword jika positional gagal
            return asyncio.run(
                UdpTransportTarget.create((host, port), timeout=timeout, retries=retries)
            )
    else:
        # pysnmp < 7: sync constructor langsung
        try:
            return UdpTransportTarget((host, port), timeout, retries)
        except Exception:
            return UdpTransportTarget((host, port), timeout=timeout, retries=retries)
