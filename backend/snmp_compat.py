"""
snmp_compat.py — Compatibility bridge for pysnmp API changes
============================================================
pysnmp < 7.0 (pysnmp-lextudio): from pysnmp.hlapi import SnmpEngine, bulkCmd, ...
pysnmp >= 7.0 (new pysnmp):      from pysnmp.hlapi.v3arch.sync import SnmpEngine, bulkCmd, ...

Import dari modul ini untuk kompatibilitas kedua versi.
"""

try:
    # pysnmp 7.x (paket baru 'pysnmp')
    from pysnmp.hlapi.v3arch.sync import (   # type: ignore[import]
        SnmpEngine,
        CommunityData,
        UdpTransportTarget,
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

except ImportError:
    try:
        # pysnmp-lextudio / pysnmp < 7 (API lama)
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

    except ImportError:
        # pysnmp tidak ada sama sekali
        SnmpEngine = CommunityData = UdpTransportTarget = ContextData = None
        ObjectType = ObjectIdentity = bulkCmd = getCmd = nextCmd = Integer32 = None
        PYSNMP_AVAILABLE = False
        PYSNMP_VERSION   = 0
