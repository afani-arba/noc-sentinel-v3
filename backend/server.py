from fastapi import FastAPI, APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, asyncio, uuid
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
import jwt
from passlib.context import CryptContext
import snmp_service
from mikrotik_api import get_api_client

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
JWT_SECRET = os.environ.get('JWT_SECRET', 'fallback_secret')

app = FastAPI()
api_router = APIRouter(prefix="/api")
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

POLL_INTERVAL = 30
polling_task = None

# ── Models ──
class UserLogin(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: str = "user"

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None

class DeviceCreate(BaseModel):
    name: str
    ip_address: str
    snmp_community: str = "public"
    snmp_port: int = 161
    api_mode: str = "rest"  # "rest" (RouterOS 7+) or "api" (RouterOS 6+)
    api_username: str = "admin"
    api_password: str = ""
    api_port: int = 443
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
    api_ssl: Optional[bool] = None
    api_plaintext_login: Optional[bool] = None
    description: Optional[str] = None

class PPPoEUserCreate(BaseModel):
    name: str
    password: str
    profile: str = "default"
    service: str = "pppoe"
    comment: str = ""

class PPPoEUserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    profile: Optional[str] = None
    service: Optional[str] = None
    comment: Optional[str] = None
    disabled: Optional[str] = None

class HotspotUserCreate(BaseModel):
    name: str
    password: str
    profile: str = "default"
    server: str = "all"
    comment: str = ""

class HotspotUserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    profile: Optional[str] = None
    server: Optional[str] = None
    comment: Optional[str] = None
    disabled: Optional[str] = None

class ReportRequest(BaseModel):
    period: str
    device_id: Optional[str] = None

# ── Auth ──
def create_token(user_data: dict) -> str:
    return jwt.encode({
        "sub": user_data["id"], "username": user_data["username"],
        "role": user_data["role"], "exp": datetime.now(timezone.utc) + timedelta(hours=24)
    }, JWT_SECRET, algorithm="HS256")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        user = await db.admin_users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def require_admin(user=Depends(get_current_user)):
    if user["role"] != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

async def require_write(user=Depends(get_current_user)):
    if user["role"] == "viewer":
        raise HTTPException(status_code=403, detail="Viewer cannot modify data")
    return user

# ── Startup ──
@app.on_event("startup")
async def startup():
    # Create default admin only
    if not await db.admin_users.find_one({"username": "admin"}):
        await db.admin_users.insert_one({
            "id": str(uuid.uuid4()), "username": "admin",
            "password": pwd_context.hash("admin123"),
            "full_name": "Administrator", "role": "administrator",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        logger.info("Default admin created: admin / admin123")
    # Drop old mock collections
    for col in ["pppoe_users", "hotspot_users", "status_checks"]:
        await db.drop_collection(col)
    # Start polling
    global polling_task
    polling_task = asyncio.create_task(polling_loop())
    logger.info("SNMP polling started (interval %ss)", POLL_INTERVAL)

@app.on_event("shutdown")
async def shutdown():
    if polling_task:
        polling_task.cancel()
    client.close()

# ── Polling ──
async def poll_single_device(device):
    did = device["id"]
    host, port, comm = device["ip_address"], device.get("snmp_port", 161), device.get("snmp_community", "public")
    try:
        result = await asyncio.wait_for(snmp_service.poll_device(host, port, comm), timeout=25)
    except (asyncio.TimeoutError, Exception):
        result = {"reachable": False, "ping": {"reachable": False, "avg": 0, "jitter": 0, "loss": 100},
                  "system": {}, "cpu": 0, "memory": {"total": 0, "used": 0, "percent": 0}, "interfaces": [], "traffic": {}}

    now = datetime.now(timezone.utc).isoformat()
    update = {"status": "online" if result["reachable"] else "offline", "last_poll": now, "last_poll_data": result}
    if result["reachable"] and result.get("system"):
        s = result["system"]
        update.update({"model": s.get("board_name", ""), "sys_name": s.get("sys_name", ""),
                        "ros_version": s.get("ros_version", ""), "uptime": s.get("uptime_formatted", ""),
                        "serial": s.get("serial", ""), "cpu_load": result.get("cpu", 0),
                        "memory_usage": result.get("memory", {}).get("percent", 0)})
    await db.devices.update_one({"id": did}, {"$set": update})

    # Bandwidth calculation from octets diff
    prev = await db.traffic_snapshots.find_one({"device_id": did})
    curr_traffic = result.get("traffic", {})
    if prev and curr_traffic:
        prev_t = prev.get("traffic", {})
        try:
            delta = max((datetime.fromisoformat(now) - datetime.fromisoformat(prev["timestamp"])).total_seconds(), 1)
        except Exception:
            delta = POLL_INTERVAL
        bw = {}
        for iface, cv in curr_traffic.items():
            pv = prev_t.get(iface, {})
            if pv:
                ind = max(0, cv["in_octets"] - pv.get("in_octets", 0))
                outd = max(0, cv["out_octets"] - pv.get("out_octets", 0))
                if ind > 2**62: ind = 0
                if outd > 2**62: outd = 0
                bw[iface] = {"download_bps": round((ind * 8) / delta), "upload_bps": round((outd * 8) / delta), "status": cv.get("status", "down")}
        if bw:
            await db.traffic_history.insert_one({
                "device_id": did, "timestamp": now, "bandwidth": bw,
                "ping_ms": result.get("ping", {}).get("avg", 0),
                "jitter_ms": result.get("ping", {}).get("jitter", 0),
                "cpu": result.get("cpu", 0), "memory_percent": result.get("memory", {}).get("percent", 0),
            })
    await db.traffic_snapshots.update_one({"device_id": did}, {"$set": {"device_id": did, "timestamp": now, "traffic": curr_traffic}}, upsert=True)
    return result

async def polling_loop():
    while True:
        try:
            devices = await db.devices.find({}, {"_id": 0}).to_list(100)
            if devices:
                await asyncio.gather(*[poll_single_device(d) for d in devices], return_exceptions=True)
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            await db.traffic_history.delete_many({"timestamp": {"$lt": cutoff}})
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll loop: {e}")
        await asyncio.sleep(POLL_INTERVAL)

# ── Helper: get MikroTik API client for a device ──
async def _get_mt_api(device_id: str) -> tuple:
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    return get_api_client(device), device

# ── Auth Routes ──
@api_router.post("/auth/login")
async def login(data: UserLogin):
    user = await db.admin_users.find_one({"username": data.username}, {"_id": 0})
    if not user or not pwd_context.verify(data.password, user["password"]):
        raise HTTPException(401, "Invalid credentials")
    return {"token": create_token(user), "user": {k: v for k, v in user.items() if k != "password"}}

@api_router.get("/auth/me")
async def get_me(user=Depends(get_current_user)):
    return {k: v for k, v in user.items() if k != "password"}

# ── Devices ──
SAFE_DEVICE_FIELDS = {"_id": 0, "snmp_community": 0, "api_password": 0, "last_poll_data": 0}

@api_router.get("/devices")
async def list_devices(user=Depends(get_current_user)):
    return await db.devices.find({}, SAFE_DEVICE_FIELDS).to_list(100)

@api_router.get("/devices/full")
async def list_devices_full(user=Depends(require_admin)):
    devs = await db.devices.find({}, {"_id": 0}).to_list(100)
    for d in devs:
        d.pop("last_poll_data", None)
    return devs

@api_router.post("/devices", status_code=201)
async def create_device(data: DeviceCreate, user=Depends(require_admin)):
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc.update({"status": "unknown", "model": "", "sys_name": "", "ros_version": "",
                "uptime": "", "serial": "", "cpu_load": 0, "memory_usage": 0,
                "created_at": datetime.now(timezone.utc).isoformat()})
    await db.devices.insert_one(doc)
    asyncio.create_task(poll_single_device(doc))
    safe = {k: v for k, v in doc.items() if k not in ("_id", "snmp_community", "api_password", "last_poll_data")}
    return safe

@api_router.put("/devices/{device_id}")
async def update_device(device_id: str, data: DeviceUpdate, user=Depends(require_admin)):
    upd = {k: v for k, v in data.model_dump().items() if v is not None}
    if not upd:
        raise HTTPException(400, "Nothing to update")
    r = await db.devices.update_one({"id": device_id}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Device not found")
    return await db.devices.find_one({"id": device_id}, SAFE_DEVICE_FIELDS)

@api_router.delete("/devices/{device_id}")
async def delete_device(device_id: str, user=Depends(require_admin)):
    r = await db.devices.delete_one({"id": device_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Device not found")
    await db.traffic_history.delete_many({"device_id": device_id})
    await db.traffic_snapshots.delete_one({"device_id": device_id})
    return {"message": "Deleted"}

@api_router.post("/devices/{device_id}/test-snmp")
async def test_snmp(device_id: str, user=Depends(get_current_user)):
    d = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Device not found")
    snmp_result = await snmp_service.test_connection(d["ip_address"], d.get("snmp_port", 161), d.get("snmp_community", "public"))
    ping_result = await snmp_service.ping_host(d["ip_address"])
    return {"snmp": snmp_result, "ping": ping_result}

@api_router.post("/devices/{device_id}/test-api")
async def test_api(device_id: str, user=Depends(get_current_user)):
    mt, _ = await _get_mt_api(device_id)
    return await mt.test_connection()

@api_router.post("/devices/{device_id}/poll")
async def trigger_poll(device_id: str, user=Depends(get_current_user)):
    d = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Device not found")
    r = await poll_single_device(d)
    return {"reachable": r["reachable"]}

@api_router.post("/devices/test-new")
async def test_new(data: DeviceCreate, user=Depends(get_current_user)):
    snmp_r = await snmp_service.test_connection(data.ip_address, data.snmp_port, data.snmp_community)
    ping_r = await snmp_service.ping_host(data.ip_address)
    mt = get_api_client(data.model_dump())
    api_r = await mt.test_connection()
    return {"snmp": snmp_r, "ping": ping_r, "api": api_r}

# ── Dashboard ──
@api_router.get("/dashboard/stats")
async def dashboard_stats(device_id: str = "", interface: str = "", user=Depends(get_current_user)):
    all_devs = await db.devices.find({}, SAFE_DEVICE_FIELDS).to_list(100)
    online = sum(1 for d in all_devs if d.get("status") == "online")
    device = await db.devices.find_one({"id": device_id}, {"_id": 0}) if device_id else None

    query = {"device_id": device_id} if device_id else {}
    history = await db.traffic_history.find(query, {"_id": 0}).sort("timestamp", -1).to_list(200)
    history.reverse()

    traffic_data = []
    for h in history[-60:]:
        try:
            time_label = datetime.fromisoformat(h["timestamp"]).strftime("%H:%M")
        except Exception:
            time_label = ""
        bw = h.get("bandwidth", {})
        if interface and interface != "all":
            ib = bw.get(interface, {})
            dl, ul = ib.get("download_bps", 0), ib.get("upload_bps", 0)
        else:
            dl = sum(v.get("download_bps", 0) for v in bw.values())
            ul = sum(v.get("upload_bps", 0) for v in bw.values())
        traffic_data.append({"time": time_label, "download": round(dl / 1e6, 2), "upload": round(ul / 1e6, 2),
                             "ping": h.get("ping_ms", 0), "jitter": h.get("jitter_ms", 0)})

    ifaces = []
    if device and device.get("last_poll_data"):
        ifaces = [i["name"] for i in device["last_poll_data"].get("interfaces", [])]

    sys_h = {"cpu": 0, "memory": 0}
    if device:
        sys_h = {"cpu": device.get("cpu_load", 0), "memory": device.get("memory_usage", 0)}

    alerts = []
    for d in all_devs:
        if d.get("status") == "offline":
            alerts.append({"id": d["id"], "type": "error", "message": f"{d['name']} OFFLINE", "time": (d.get("last_poll") or "")[:16]})
        if d.get("cpu_load", 0) > 80:
            alerts.append({"id": d["id"]+"c", "type": "warning", "message": f"CPU {d['cpu_load']}% on {d['name']}", "time": (d.get("last_poll") or "")[:16]})
        if d.get("memory_usage", 0) > 80:
            alerts.append({"id": d["id"]+"m", "type": "warning", "message": f"Memory {d['memory_usage']}% on {d['name']}", "time": (d.get("last_poll") or "")[:16]})
    if not alerts:
        alerts.append({"id": "ok", "type": "success", "message": "All systems normal", "time": datetime.now(timezone.utc).strftime("%H:%M")})

    last = traffic_data[-1] if traffic_data else {"download": 0, "upload": 0}
    return {
        "devices": {"total": len(all_devs), "online": online},
        "total_bandwidth": {"download": last["download"], "upload": last["upload"]},
        "traffic_data": traffic_data, "alerts": alerts,
        "system_health": sys_h, "interfaces": ifaces,
        "selected_device": {"name": device.get("name",""), "model": device.get("model",""),
                            "uptime": device.get("uptime",""), "ros_version": device.get("ros_version",""),
                            "status": device.get("status",""), "ip_address": device.get("ip_address","")} if device else None,
    }

@api_router.get("/dashboard/interfaces")
async def dashboard_interfaces(device_id: str = "", user=Depends(get_current_user)):
    if not device_id:
        return ["all"]
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device or not device.get("last_poll_data"):
        return ["all"]
    # Filter out interfaces with empty names
    interfaces = [i["name"] for i in device["last_poll_data"].get("interfaces", []) if i.get("name")]
    return ["all"] + interfaces

# ── PPPoE Users (via MikroTik REST API) ──
@api_router.get("/pppoe-users")
async def list_pppoe_users(device_id: str = "", search: str = "", user=Depends(get_current_user)):
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt_api(device_id)
        secrets = await mt.list_pppoe_secrets()
        active_list = await mt.list_pppoe_active()
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")
    active_names = {a.get("name", "") for a in active_list}
    result = []
    for s in secrets:
        s["is_online"] = s.get("name", "") in active_names
        if search and search.lower() not in str(s).lower():
            continue
        result.append(s)
    return result

@api_router.post("/pppoe-users", status_code=201)
async def create_pppoe_user(device_id: str, data: PPPoEUserCreate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    body = {k: v for k, v in data.model_dump().items() if v}
    try:
        return await mt.create_pppoe_secret(body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")

@api_router.put("/pppoe-users/{mt_id}")
async def update_pppoe_user(mt_id: str, device_id: str, data: PPPoEUserUpdate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    body = {k: v for k, v in data.model_dump().items() if v is not None}
    try:
        return await mt.update_pppoe_secret(mt_id, body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")

@api_router.delete("/pppoe-users/{mt_id}")
async def delete_pppoe_user(mt_id: str, device_id: str, user=Depends(require_admin)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.delete_pppoe_secret(mt_id)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")

@api_router.get("/pppoe-active")
async def list_pppoe_active(device_id: str, user=Depends(get_current_user)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.list_pppoe_active()
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")

# ── Hotspot Users (via MikroTik REST API) ──
@api_router.get("/hotspot-users")
async def list_hotspot_users(device_id: str = "", search: str = "", user=Depends(get_current_user)):
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt_api(device_id)
        users = await mt.list_hotspot_users()
        active_list = await mt.list_hotspot_active()
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")
    active_names = {a.get("user", "") for a in active_list}
    result = []
    for u in users:
        u["is_online"] = u.get("name", "") in active_names
        if search and search.lower() not in str(u).lower():
            continue
        result.append(u)
    return result

@api_router.post("/hotspot-users", status_code=201)
async def create_hotspot_user(device_id: str, data: HotspotUserCreate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    body = {k: v for k, v in data.model_dump().items() if v}
    try:
        return await mt.create_hotspot_user(body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")

@api_router.put("/hotspot-users/{mt_id}")
async def update_hotspot_user(mt_id: str, device_id: str, data: HotspotUserUpdate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    body = {k: v for k, v in data.model_dump().items() if v is not None}
    try:
        return await mt.update_hotspot_user(mt_id, body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")

@api_router.delete("/hotspot-users/{mt_id}")
async def delete_hotspot_user(mt_id: str, device_id: str, user=Depends(require_admin)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.delete_hotspot_user(mt_id)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")

@api_router.get("/hotspot-active")
async def list_hotspot_active(device_id: str, user=Depends(get_current_user)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.list_hotspot_active()
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")

# ── Reports ──
@api_router.post("/reports/generate")
async def generate_report(data: ReportRequest, user=Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    hours = {"daily": 24, "weekly": 168, "monthly": 720}
    h = hours.get(data.period, 24)
    start = now - timedelta(hours=h)
    label = {"daily": "Daily Report", "weekly": "Weekly Report", "monthly": "Monthly Report"}.get(data.period, "Report")

    all_devs = await db.devices.find({}, {"_id": 0, "snmp_community": 0, "api_password": 0, "last_poll_data": 0}).to_list(100)
    query = {"timestamp": {"$gte": start.isoformat()}}
    if data.device_id:
        query["device_id"] = data.device_id
    history = await db.traffic_history.find(query, {"_id": 0}).sort("timestamp", 1).to_list(5000)

    trend = []
    for h_item in history:
        try:
            dt = datetime.fromisoformat(h_item["timestamp"])
            tl = dt.strftime("%H:%M") if data.period == "daily" else dt.strftime("%d/%m %H:%M")
        except Exception:
            tl = ""
        bw = h_item.get("bandwidth", {})
        dl = sum(v.get("download_bps", 0) for v in bw.values())
        ul = sum(v.get("upload_bps", 0) for v in bw.values())
        trend.append({"time": tl, "download": round(dl / 1e6, 2), "upload": round(ul / 1e6, 2),
                      "ping": h_item.get("ping_ms", 0), "jitter": h_item.get("jitter_ms", 0)})

    if trend:
        avg_dl = round(sum(t["download"] for t in trend) / len(trend), 2)
        avg_ul = round(sum(t["upload"] for t in trend) / len(trend), 2)
        peak_dl = round(max(t["download"] for t in trend), 2)
        peak_ul = round(max(t["upload"] for t in trend), 2)
        avg_ping = round(sum(t["ping"] for t in trend) / len(trend), 1)
        avg_jitter = round(sum(t["jitter"] for t in trend) / len(trend), 1)
    else:
        avg_dl = avg_ul = peak_dl = peak_ul = avg_ping = avg_jitter = 0

    dev_summary = [{"name": d["name"], "ip_address": d.get("ip_address",""), "model": d.get("model",""),
                    "status": d.get("status","unknown"), "cpu": d.get("cpu_load",0),
                    "memory": d.get("memory_usage",0), "uptime": d.get("uptime","")} for d in all_devs]
    return {
        "label": label, "period": data.period, "generated_at": now.isoformat(),
        "start_date": start.isoformat(), "end_date": now.isoformat(),
        "summary": {"devices": {"total": len(all_devs), "online": sum(1 for d in all_devs if d.get("status")=="online")},
                     "avg_bandwidth": {"download": avg_dl, "upload": avg_ul},
                     "peak_bandwidth": {"download": peak_dl, "upload": peak_ul},
                     "avg_ping": avg_ping, "avg_jitter": avg_jitter},
        "traffic_trend": trend[-300:], "device_summary": dev_summary,
    }

# ── Admin Users ──
@api_router.get("/admin/users")
async def list_admin_users(user=Depends(require_admin)):
    return await db.admin_users.find({}, {"_id": 0, "password": 0}).to_list(100)

@api_router.post("/admin/users", status_code=201)
async def create_admin_user(data: UserCreate, user=Depends(require_admin)):
    if await db.admin_users.find_one({"username": data.username}):
        raise HTTPException(400, "Username exists")
    if data.role not in ["administrator", "viewer", "user"]:
        raise HTTPException(400, "Invalid role")
    doc = {"id": str(uuid.uuid4()), "username": data.username,
           "password": pwd_context.hash(data.password), "full_name": data.full_name,
           "role": data.role, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.admin_users.insert_one(doc)
    return {k: v for k, v in doc.items() if k not in ("_id", "password")}

@api_router.put("/admin/users/{user_id}")
async def update_admin_user(user_id: str, data: UserUpdate, user=Depends(require_admin)):
    upd = {}
    if data.full_name is not None: upd["full_name"] = data.full_name
    if data.role is not None:
        if data.role not in ["administrator","viewer","user"]: raise HTTPException(400,"Invalid role")
        upd["role"] = data.role
    if data.password is not None: upd["password"] = pwd_context.hash(data.password)
    if not upd: raise HTTPException(400, "Nothing to update")
    r = await db.admin_users.update_one({"id": user_id}, {"$set": upd})
    if r.matched_count == 0: raise HTTPException(404, "Not found")
    return await db.admin_users.find_one({"id": user_id}, {"_id": 0, "password": 0})

@api_router.delete("/admin/users/{user_id}")
async def delete_admin_user(user_id: str, user=Depends(require_admin)):
    target = await db.admin_users.find_one({"id": user_id}, {"_id": 0})
    if not target: raise HTTPException(404, "Not found")
    if target["id"] == user["id"]: raise HTTPException(400, "Cannot delete yourself")
    await db.admin_users.delete_one({"id": user_id})
    return {"message": "Deleted"}

@api_router.get("/health")
async def health():
    return {"status": "ok"}

app.include_router(api_router)
app.add_middleware(CORSMiddleware, allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS','*').split(','), allow_methods=["*"], allow_headers=["*"])
