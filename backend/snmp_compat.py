"""
snmp_compat.py — Compatibility bridge for pysnmp API changes
============================================================
Mendukung:
  pysnmp >= 7.x (paket 'pysnmp'):
      SnmpEngine, CommunityData dll di pysnmp.hlapi.v3arch
      bulkCmd, getCmd, nextCmd di pysnmp.hlapi.v3arch.sync atau pysnmp.hlapi
  pysnmp-lextudio / pysnmp < 7 (lama):
      semua di pysnmp.hlapi langsung

Import dari modul ini agar kompatibel kedua versi.
"""
import logging
logger = logging.getLogger(__name__)

PYSNMP_AVAILABLE = False
PYSNMP_VERSION   = 0

SnmpEngine = CommunityData = UdpTransportTarget = ContextData = None
ObjectType = ObjectIdentity = bulkCmd = getCmd = nextCmd = Integer32 = None

# ── Attempt 1: pysnmp 7.x — class-level objects di v3arch ───────────────────
try:
    from pysnmp.hlapi.v3arch import (   # type: ignore[import]
        SnmpEngine,
        CommunityData,
        UdpTransportTarget,
        ContextData,
        ObjectType,
        ObjectIdentity,
    )
    # bulkCmd/getCmd/nextCmd bisa di v3arch.sync atau langsung di hlapi
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
        # pysnmp 7.x mungkin hanya punya async — buat stub agar tidak crash
        def bulkCmd(*a, **k): return iter([])   # type: ignore
        def getCmd(*a, **k):  return iter([])   # type: ignore
        def nextCmd(*a, **k): return iter([])   # type: ignore

    try:
        from pysnmp.proto.rfc1902 import Integer32  # type: ignore[import]
    except ImportError:
        Integer32 = None

    PYSNMP_AVAILABLE = True
    PYSNMP_VERSION   = 7
    logger.debug("snmp_compat: pysnmp 7.x loaded via hlapi.v3arch")

except ImportError:
    # ── Attempt 2: pysnmp-lextudio / pysnmp < 7 ─────────────────────────────
    try:
        from pysnmp.hlapi import (   # type: ignore[import]
            SnmpEngine,
            CommunityData,
            UdpTransportTarget,
            ContextData,
            ObjectType,
            ObjectIdentity,
            bulkCmd,
            getCmd,
            nextCmd,
            Integer32,
        )
        PYSNMP_AVAILABLE = True
        PYSNMP_VERSION   = 6
        logger.debug("snmp_compat: pysnmp-lextudio (v6) loaded via hlapi")

    except ImportError:
        logger.warning("snmp_compat: pysnmp tidak terinstall — SNMP monitoring nonaktif")
