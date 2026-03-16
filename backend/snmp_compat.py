"""
snmp_compat.py — Simple bridge for pysnmp import compatibility
=============================================================
pysnmp-lextudio >= 6.0.0: from pysnmp.hlapi import ...  (sync, works perfectly)
pysnmp >= 4.4: same import path
"""
import logging
logger = logging.getLogger(__name__)

PYSNMP_AVAILABLE = False
PYSNMP_VERSION   = 0

SnmpEngine = CommunityData = UdpTransportTarget = ContextData = None
ObjectType = ObjectIdentity = bulkCmd = getCmd = nextCmd = Integer32 = None

try:
    from pysnmp.hlapi import (   # type: ignore[import]
        SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity, bulkCmd, getCmd, nextCmd,
    )
    try:
        from pysnmp.proto.rfc1902 import Integer32  # type: ignore[import]
    except ImportError:
        Integer32 = None

    PYSNMP_AVAILABLE = True
    # Deteksi versi
    try:
        import pysnmp
        ver_str = getattr(pysnmp, "__version__", "0")
        PYSNMP_VERSION = int(str(ver_str).split(".")[0])
    except Exception:
        PYSNMP_VERSION = 6

    logger.warning(f"snmp_compat: pysnmp OK (v{PYSNMP_VERSION}, via pysnmp.hlapi)")

except ImportError as e:
    logger.warning(f"snmp_compat: pysnmp TIDAK TERINSTALL — {e}")


def make_udp_transport(host: str, port: int = 161, timeout: int = 5, retries: int = 1):
    """Buat UdpTransportTarget (sync constructor)."""
    if not PYSNMP_AVAILABLE or UdpTransportTarget is None:
        raise RuntimeError("pysnmp tidak terinstall")
    try:
        return UdpTransportTarget((host, port), timeout, retries)
    except Exception:
        return UdpTransportTarget((host, port), timeout=timeout, retries=retries)
