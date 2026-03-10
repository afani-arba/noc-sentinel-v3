"""
Devices router: CRUD + dashboard + SNMP test + MikroTik API test.
"""
import uuid
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from core.db import get_db
from core.auth import get_current_user, require_admin
import snmp_service
from mikrotik_api import get_api_client
from core.polling import poll_single_device

router = APIRouter(tags=["devices"])
logger = logging.getLogger(__name__)

SAFE_DEVICE_FIELDS = {"_id": 0, "snmp_community": 0, "api_password": 0, "last_poll_data": 0}


class DeviceCreate(BaseModel):
    name: str
    ip_address: str
    snmp_community: str = "public"
    snmp_port: int = 161
    api_mode: str = "rest"
    api_username: str = "admin"
    api_password: str = ""
    api_port: Optional[int] = None
    use_https: bool = False
    api_ssl: bool = True
    api_plaintext_login: bool = True
    description: str = ""


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    snmp_community: Optional[str] = None
    snmp_port: Optional[int] = None
    api_mode: Optional[str] = None
    api_username: Optional[str] = None
    api_password: Optional[str] = None
    api_port: Optional[int] = None
    use_https: Optional[bool] = None
    api_ssl: Optional[bool] = None
    api_plaintext_login: Optional[bool] = None
    description: Optional[str] = None


def filter_devices_for_user(devices: list, user: dict) -> list:
    if user.get("role") == "administrator":
        return devices
    allowed = user.get("allowed_devices", [])
    if not allowed:
        return []
    return [d for d in devices if d.get("id") in allowed]


@router.get("/devices")
async def list_devices(user=Depends(get_current_user)):
    db = get_db()
    devs = await db.devices.find({}, SAFE_DEVICE_FIELDS).to_list(100)
    return filter_devices_for_user(devs, user)


@router.get("/devices/full")
async def list_devices_full(user=Depends(require_admin)):
    db = get_db()
    devs = await db.devices.find({}, {"_id": 0}).to_list(100)
    for d in devs:
        d.pop("last_poll_data", None)
    return devs


@router.get("/devices/all")
async def list_all_devices_for_admin(user=Depends(require_admin)):
    db = get_db()
    return await db.devices.find({}, {"_id": 0, "id": 1, "name": 1, "ip_address": 1}).to_list(100)


@router.post("/devices", status_code=201)
async def create_device(data: DeviceCreate, user=Depends(require_admin)):
    db = get_db()
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc.update({
        "status": "unknown", "model": "", "sys_name": "", "ros_version": "",
        "uptime": "", "serial": "", "cpu_load": 0, "memory_usage": 0,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    await db.devices.insert_one(doc)
    asyncio.create_task(poll_single_device(doc))
    return {k: v for k, v in doc.items() if k not in ("_id", "snmp_community", "api_password", "last_poll_data")}


@router.put("/devices/{device_id}")
async def update_device(device_id: str, data: DeviceUpdate, user=Depends(require_admin)):
    db = get_db()
    upd = {k: v for k, v in data.model_dump().items() if v is not None}
    if not upd:
        raise HTTPException(400, "Nothing to update")
    r = await db.devices.update_one({"id": device_id}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Device not found")
    return await db.devices.find_one({"id": device_id}, SAFE_DEVICE_FIELDS)


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, user=Depends(require_admin)):
    db = get_db()
    r = await db.devices.delete_one({"id": device_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Device not found")
    await db.traffic_history.delete_many({"device_id": device_id})
    await db.traffic_snapshots.delete_one({"device_id": device_id})
    return {"message": "Deleted"}


@router.post("/devices/{device_id}/test-snmp")
async def test_snmp(device_id: str, user=Depends(get_current_user)):
    db = get_db()
    d = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Device not found")
    snmp_result = await snmp_service.test_connection(d["ip_address"], d.get("snmp_port", 161), d.get("snmp_community", "public"))
    ping_result = await snmp_service.ping_host(d["ip_address"])
    return {"snmp": snmp_result, "ping": ping_result}


@router.post("/devices/{device_id}/test-api")
async def test_api(device_id: str, user=Depends(get_current_user)):
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    return await mt.test_connection()


@router.get("/devices/{device_id}/system-resource")
async def get_system_resource(device_id: str, user=Depends(get_current_user)):
    """Ambil info CPU, memory, uptime langsung dari MikroTik REST API (ROS 7.x)."""
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    try:
        r = await mt.get_system_resource()
        return r
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


@router.get("/devices/{device_id}/interfaces")
async def get_interfaces(device_id: str, user=Depends(get_current_user)):
    """List semua interface dari MikroTik (nama, status, type, MAC)."""
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    try:
        ifaces = await mt.list_interfaces()
        return ifaces
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


@router.get("/devices/{device_id}/ip-addresses")
async def get_ip_addresses(device_id: str, user=Depends(get_current_user)):
    """List semua IP address yang dikonfigurasi di MikroTik."""
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    try:
        addrs = await mt.list_ip_addresses()
        return addrs
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


@router.get("/devices/{device_id}/system-health")
async def get_system_health(device_id: str, user=Depends(get_current_user)):
    """
    Ambil data sensor hardware dari MikroTik REST API /rest/system/health.
    ROS 7.x: cpu-temperature, board-temperature, voltage, power-consumption.
    Lebih reliable dari SNMP untuk device yang tidak support MikroTik private MIB.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    try:
        health = await mt.get_system_health()
        return health
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


@router.post("/devices/{device_id}/poll")
async def trigger_poll(device_id: str, user=Depends(get_current_user)):
    db = get_db()
    d = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Device not found")
    r = await poll_single_device(d)
    return {"reachable": r["reachable"]}


@router.post("/devices/test-new")
async def test_new(data: DeviceCreate, user=Depends(get_current_user)):
    snmp_r = await snmp_service.test_connection(data.ip_address, data.snmp_port, data.snmp_community)
    ping_r = await snmp_service.ping_host(data.ip_address)
    mt = get_api_client(data.model_dump())
    api_r = await mt.test_connection()
    return {"snmp": snmp_r, "ping": ping_r, "api": api_r}


# ── Dashboard ──
@router.get("/dashboard/stats")
async def dashboard_stats(device_id: str = "", interface: str = "", user=Depends(get_current_user)):
    db = get_db()
    all_devs = await db.devices.find({}, SAFE_DEVICE_FIELDS).to_list(100)
    online = sum(1 for d in all_devs if d.get("status") == "online")
    device = await db.devices.find_one({"id": device_id}, {"_id": 0}) if device_id else None

    query = {"device_id": device_id} if device_id else {}
    history = await db.traffic_history.find(query, {"_id": 0}).sort("timestamp", -1).to_list(200)
    history.reverse()

    traffic_data = []
    for h in history[-60:]:
        try:
            utc_time = datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00"))
            local_time = utc_time.replace(tzinfo=None) + timedelta(hours=7)
            time_label = local_time.strftime("%H:%M")
        except Exception:
            time_label = ""
        bw = h.get("bandwidth", {})
        if interface and interface != "all":
            ib = bw.get(interface, {})
            dl, ul = ib.get("download_bps", 0), ib.get("upload_bps", 0)
        else:
            dl = sum(v.get("download_bps", 0) for v in bw.values())
            ul = sum(v.get("upload_bps", 0) for v in bw.values())
        ping_data = h
        traffic_data.append({
            "time": time_label, "download": round(dl / 1e6, 2), "upload": round(ul / 1e6, 2),
            "ping": h.get("ping_ms", 0), "jitter": h.get("jitter_ms", 0)
        })

    ifaces = []
    if device and device.get("last_poll_data"):
        ifaces = [i["name"] for i in device["last_poll_data"].get("interfaces", [])]

    sys_h = {"cpu": 0, "memory": 0, "cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0}
    if device:
        sys_h = {
            "cpu": device.get("cpu_load", 0), "memory": device.get("memory_usage", 0),
            "cpu_temp": device.get("cpu_temp", 0), "board_temp": device.get("board_temp", 0),
            "voltage": device.get("voltage", 0), "power": device.get("power", 0),
        }

    alerts = []
    for d in all_devs:
        if d.get("status") == "offline":
            alerts.append({"id": d["id"], "type": "error", "message": f"{d['name']} OFFLINE", "time": (d.get("last_poll") or "")[:16]})
        if d.get("cpu_load", 0) > 80:
            alerts.append({"id": d["id"] + "c", "type": "warning", "message": f"CPU {d['cpu_load']}% on {d['name']}", "time": (d.get("last_poll") or "")[:16]})
        if d.get("memory_usage", 0) > 80:
            alerts.append({"id": d["id"] + "m", "type": "warning", "message": f"Memory {d['memory_usage']}% on {d['name']}", "time": (d.get("last_poll") or "")[:16]})
    if not alerts:
        alerts.append({"id": "ok", "type": "success", "message": "All systems normal", "time": datetime.now(timezone.utc).strftime("%H:%M")})

    last = traffic_data[-1] if traffic_data else {"download": 0, "upload": 0}
    return {
        "devices": {"total": len(all_devs), "online": online},
        "total_bandwidth": {"download": last["download"], "upload": last["upload"]},
        "traffic_data": traffic_data, "alerts": alerts,
        "system_health": sys_h, "interfaces": ifaces,
        "selected_device": {
            "name": device.get("name", ""), "model": device.get("model", ""),
            "identity": device.get("identity", device.get("sys_name", "")),
            "uptime": device.get("uptime", ""), "ros_version": device.get("ros_version", ""),
            "architecture": device.get("architecture", ""),
            "status": device.get("status", ""), "ip_address": device.get("ip_address", "")
        } if device else None,
    }


@router.get("/dashboard/interfaces")
async def dashboard_interfaces(device_id: str = "", user=Depends(get_current_user)):
    if not device_id:
        return ["all"]
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device or not device.get("last_poll_data"):
        return ["all"]
    interfaces = [i["name"] for i in device["last_poll_data"].get("interfaces", []) if i.get("name")]
    return ["all"] + interfaces
