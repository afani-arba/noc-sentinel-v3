"""
SNMP Service for MikroTik device monitoring.
"""
import asyncio
import subprocess
import re
import logging
from pysnmp.hlapi.asyncio import (
    getCmd, nextCmd,
    SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity,
)

logger = logging.getLogger(__name__)

# Standard MIB-2 OIDs
OID_SYS_DESCR = '1.3.6.1.2.1.1.1.0'
OID_SYS_UPTIME = '1.3.6.1.2.1.1.3.0'
OID_SYS_NAME = '1.3.6.1.2.1.1.5.0'
OID_IF_DESCR = '1.3.6.1.2.1.2.2.1.2'
OID_IF_SPEED = '1.3.6.1.2.1.2.2.1.5'
OID_IF_OPER_STATUS = '1.3.6.1.2.1.2.2.1.8'
OID_IF_IN_OCTETS = '1.3.6.1.2.1.2.2.1.10'
OID_IF_OUT_OCTETS = '1.3.6.1.2.1.2.2.1.16'
OID_IF_HC_IN_OCTETS = '1.3.6.1.2.1.31.1.1.1.6'
OID_IF_HC_OUT_OCTETS = '1.3.6.1.2.1.31.1.1.1.10'
OID_HR_PROCESSOR_LOAD = '1.3.6.1.2.1.25.3.3.1.2'
OID_HR_STORAGE_DESCR = '1.3.6.1.2.1.25.2.3.1.3'
OID_HR_STORAGE_UNITS = '1.3.6.1.2.1.25.2.3.1.4'
OID_HR_STORAGE_SIZE = '1.3.6.1.2.1.25.2.3.1.5'
OID_HR_STORAGE_USED = '1.3.6.1.2.1.25.2.3.1.6'
OID_MT_BOARD = '1.3.6.1.4.1.14988.1.1.7.3.0'
OID_MT_SERIAL = '1.3.6.1.4.1.14988.1.1.7.1.0'
OID_MT_FIRMWARE = '1.3.6.1.4.1.14988.1.1.7.4.0'


async def snmp_get(host, port, community, oid, timeout=4, retries=1):
    try:
        engine = SnmpEngine()
        result = await getCmd(
            engine, CommunityData(community),
            UdpTransportTarget((host, port), timeout=timeout, retries=retries),
            ContextData(), ObjectType(ObjectIdentity(oid)),
        )
        errorIndication, errorStatus, _, varBinds = result
        engine.closeDispatcher()
        if errorIndication or errorStatus:
            return None
        for varBind in varBinds:
            return str(varBind[1])
    except Exception as e:
        logger.debug(f"SNMP GET {host} {oid}: {e}")
        return None


async def snmp_walk(host, port, community, oid, timeout=4, retries=1):
    results = {}
    try:
        engine = SnmpEngine()
        async for (errorIndication, errorStatus, _, varBinds) in nextCmd(
            engine, CommunityData(community),
            UdpTransportTarget((host, port), timeout=timeout, retries=retries),
            ContextData(), ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            if errorIndication or errorStatus:
                break
            for varBind in varBinds:
                idx = str(varBind[0]).split('.')[-1]
                results[idx] = str(varBind[1])
        engine.closeDispatcher()
    except Exception as e:
        logger.debug(f"SNMP WALK {host} {oid}: {e}")
    return results


async def test_connection(host, port, community):
    result = await snmp_get(host, port, community, OID_SYS_NAME)
    if result is not None:
        return {"success": True, "sys_name": result}
    return {"success": False, "error": "SNMP timeout or unreachable"}


async def get_system_info(host, port, community):
    info = {}
    keys = ["sys_name", "sys_descr", "sys_uptime", "board_name", "serial", "firmware"]
    oids = [OID_SYS_NAME, OID_SYS_DESCR, OID_SYS_UPTIME, OID_MT_BOARD, OID_MT_SERIAL, OID_MT_FIRMWARE]
    results = await asyncio.gather(*[snmp_get(host, port, community, o) for o in oids], return_exceptions=True)
    for key, val in zip(keys, results):
        info[key] = str(val) if val and not isinstance(val, Exception) else ""
    try:
        ticks = int(info.get("sys_uptime", "0"))
        s = ticks // 100
        info["uptime_formatted"] = f"{s // 86400}d {(s % 86400) // 3600}h {(s % 3600) // 60}m"
        info["uptime_seconds"] = s
    except (ValueError, TypeError):
        info["uptime_formatted"] = "N/A"
        info["uptime_seconds"] = 0
    descr = info.get("sys_descr", "")
    m = re.search(r'RouterOS\s+([\d.]+)', descr)
    info["ros_version"] = m.group(1) if m else ""
    return info


async def get_interfaces(host, port, community):
    names = await snmp_walk(host, port, community, OID_IF_DESCR)
    statuses = await snmp_walk(host, port, community, OID_IF_OPER_STATUS)
    speeds = await snmp_walk(host, port, community, OID_IF_SPEED)
    interfaces = []
    for idx, name in names.items():
        interfaces.append({
            "index": idx, "name": name,
            "status": "up" if statuses.get(idx, "2") == "1" else "down",
            "speed": int(speeds.get(idx, "0")),
        })
    return interfaces


async def get_interface_traffic(host, port, community):
    names = await snmp_walk(host, port, community, OID_IF_DESCR)
    in_octets = await snmp_walk(host, port, community, OID_IF_HC_IN_OCTETS)
    if not in_octets:
        in_octets = await snmp_walk(host, port, community, OID_IF_IN_OCTETS)
    out_octets = await snmp_walk(host, port, community, OID_IF_HC_OUT_OCTETS)
    if not out_octets:
        out_octets = await snmp_walk(host, port, community, OID_IF_OUT_OCTETS)
    statuses = await snmp_walk(host, port, community, OID_IF_OPER_STATUS)
    traffic = {}
    for idx, name in names.items():
        try:
            traffic[name] = {
                "index": idx,
                "in_octets": int(in_octets.get(idx, "0")),
                "out_octets": int(out_octets.get(idx, "0")),
                "status": "up" if statuses.get(idx, "2") == "1" else "down",
            }
        except (ValueError, TypeError):
            pass
    return traffic


async def get_cpu_load(host, port, community):
    loads = await snmp_walk(host, port, community, OID_HR_PROCESSOR_LOAD)
    if not loads:
        return 0
    values = [int(v) for v in loads.values() if v.isdigit()]
    return round(sum(values) / len(values)) if values else 0


async def get_memory_usage(host, port, community):
    descrs = await snmp_walk(host, port, community, OID_HR_STORAGE_DESCR)
    units = await snmp_walk(host, port, community, OID_HR_STORAGE_UNITS)
    sizes = await snmp_walk(host, port, community, OID_HR_STORAGE_SIZE)
    useds = await snmp_walk(host, port, community, OID_HR_STORAGE_USED)
    memory = {"total": 0, "used": 0, "percent": 0}
    for idx, descr in descrs.items():
        if "memory" in descr.lower() or "ram" in descr.lower():
            try:
                unit = int(units.get(idx, "1"))
                total = int(sizes.get(idx, "0")) * unit
                used = int(useds.get(idx, "0")) * unit
                if total > memory["total"]:
                    memory = {"total": total, "used": used, "percent": round((used / total) * 100) if total > 0 else 0}
            except (ValueError, TypeError, ZeroDivisionError):
                pass
    return memory


async def ping_host(host, count=3, timeout=2):
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", str(count), "-W", str(timeout), host,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=count * timeout + 5)
        output = stdout.decode()
        rtt = re.search(r'rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)', output)
        loss = re.search(r'(\d+)% packet loss', output)
        if rtt:
            return {"reachable": True, "min": float(rtt.group(1)), "avg": float(rtt.group(2)),
                    "max": float(rtt.group(3)), "jitter": float(rtt.group(4)),
                    "loss": int(loss.group(1)) if loss else 0}
        return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}
    except Exception as e:
        logger.debug(f"Ping {host}: {e}")
        return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}


async def poll_device(host, port, community):
    # Run ping and SNMP checks in parallel - don't skip SNMP if ping fails
    # Many routers block ICMP but allow SNMP
    ping_task = ping_host(host)
    snmp_test_task = snmp_get(host, port, community, OID_SYS_NAME, timeout=5, retries=2)
    
    ping, snmp_test = await asyncio.gather(ping_task, snmp_test_task, return_exceptions=True)
    
    if isinstance(ping, Exception):
        ping = {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}
    
    # Check if SNMP is reachable (even if ping fails)
    snmp_reachable = snmp_test is not None and not isinstance(snmp_test, Exception)
    
    if not snmp_reachable:
        return {"reachable": False, "ping": ping, "system": {}, "cpu": 0,
                "memory": {"total": 0, "used": 0, "percent": 0}, "interfaces": [], "traffic": {}}
    
    # SNMP is reachable, fetch all data
    sys_info, cpu, memory, ifaces, traffic = await asyncio.gather(
        get_system_info(host, port, community),
        get_cpu_load(host, port, community),
        get_memory_usage(host, port, community),
        get_interfaces(host, port, community),
        get_interface_traffic(host, port, community),
        return_exceptions=True,
    )
    return {
        "reachable": True, "ping": ping,
        "system": sys_info if not isinstance(sys_info, Exception) else {},
        "cpu": cpu if not isinstance(cpu, Exception) else 0,
        "memory": memory if not isinstance(memory, Exception) else {"total": 0, "used": 0, "percent": 0},
        "interfaces": ifaces if not isinstance(ifaces, Exception) else [],
        "traffic": traffic if not isinstance(traffic, Exception) else {},
    }
