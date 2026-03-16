"""
snmp_compat.py — pysnmp availability check
==========================================
pysnmp-lextudio 6.x menggunakan ASYNC API: pysnmp.hlapi.asyncio
Modul ini hanya untuk cek ketersediaan pysnmp.
Import sebenarnya dilakukan langsung di snmp_poller.py.
"""
import logging
logger = logging.getLogger(__name__)

PYSNMP_AVAILABLE = False
PYSNMP_VERSION   = 0

try:
    from pysnmp.hlapi.asyncio import (   # type: ignore[import]
        getCmd, SnmpEngine, CommunityData,
        UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity,
    )
    try:
        import pysnmp
        ver_str = getattr(pysnmp, "__version__", "6")
        PYSNMP_VERSION = int(str(ver_str).split(".")[0])
    except Exception:
        PYSNMP_VERSION = 6

    PYSNMP_AVAILABLE = True
    logger.warning(f"snmp_compat: pysnmp-lextudio v{PYSNMP_VERSION} (hlapi.asyncio) OK")

except ImportError as e:
    logger.warning(f"snmp_compat: pysnmp TIDAK TERINSTALL — {e}")
    logger.warning("snmp_compat: Install: pip install pyasn1==0.5.1 pysmi-lextudio==1.3.3 pysnmp-lextudio==6.2.0")
