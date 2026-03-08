from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import jwt
from passlib.context import CryptContext
import random

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

# --- Models ---
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

class TokenResponse(BaseModel):
    token: str
    user: dict

class PPPoEUserCreate(BaseModel):
    username: str
    password: str
    profile: str
    service: str = "pppoe"
    ip_address: str = ""
    mac_address: str = ""
    comment: str = ""

class PPPoEUserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    profile: Optional[str] = None
    service: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    comment: Optional[str] = None
    status: Optional[str] = None

class HotspotUserCreate(BaseModel):
    username: str
    password: str
    profile: str
    server: str = "hotspot1"
    mac_address: str = ""
    limit_uptime: str = ""
    limit_bytes_total: str = ""
    comment: str = ""

class HotspotUserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    profile: Optional[str] = None
    server: Optional[str] = None
    mac_address: Optional[str] = None
    limit_uptime: Optional[str] = None
    limit_bytes_total: Optional[str] = None
    comment: Optional[str] = None
    status: Optional[str] = None

class DeviceCreate(BaseModel):
    name: str
    ip_address: str
    port: int = 8728
    username: str = "admin"
    password: str = ""
    description: str = ""

class ReportRequest(BaseModel):
    period: str  # "daily", "weekly", "monthly"
    device_id: Optional[str] = None

# --- Auth Helpers ---
def create_token(user_data: dict) -> str:
    payload = {
        "sub": user_data["id"],
        "username": user_data["username"],
        "role": user_data["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=24)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

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

# --- Seed Data ---
@app.on_event("startup")
async def seed_data():
    admin = await db.admin_users.find_one({"username": "admin"})
    if not admin:
        await db.admin_users.insert_one({
            "id": str(uuid.uuid4()),
            "username": "admin",
            "password": pwd_context.hash("admin123"),
            "full_name": "Administrator",
            "role": "administrator",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        logger.info("Default admin user created: admin / admin123")

    pppoe_count = await db.pppoe_users.count_documents({})
    if pppoe_count == 0:
        profiles = ["10Mbps", "20Mbps", "50Mbps", "100Mbps"]
        for i in range(25):
            await db.pppoe_users.insert_one({
                "id": str(uuid.uuid4()),
                "username": f"pppoe_user_{i+1}",
                "password": f"pass{i+1}",
                "profile": random.choice(profiles),
                "service": "pppoe",
                "ip_address": f"10.0.{random.randint(1,10)}.{random.randint(1,254)}",
                "mac_address": ":".join([f"{random.randint(0,255):02x}" for _ in range(6)]),
                "status": random.choice(["active", "active", "active", "disabled"]),
                "uptime": f"{random.randint(0,30)}d {random.randint(0,23)}h",
                "bytes_in": random.randint(100000000, 50000000000),
                "bytes_out": random.randint(50000000, 10000000000),
                "comment": f"Customer {i+1}",
                "device_id": "default",
                "created_at": datetime.now(timezone.utc).isoformat()
            })
        logger.info("Seeded 25 PPPoE users")

    hotspot_count = await db.hotspot_users.count_documents({})
    if hotspot_count == 0:
        profiles = ["1hour", "3hour", "1day", "1week", "1month"]
        servers = ["hotspot1", "hotspot2"]
        for i in range(25):
            await db.hotspot_users.insert_one({
                "id": str(uuid.uuid4()),
                "username": f"hotspot_user_{i+1}",
                "password": f"hs{i+1}",
                "profile": random.choice(profiles),
                "server": random.choice(servers),
                "mac_address": ":".join([f"{random.randint(0,255):02x}" for _ in range(6)]),
                "limit_uptime": f"{random.randint(1,24)}h",
                "limit_bytes_total": str(random.randint(100, 5000)) + "M",
                "status": random.choice(["active", "active", "expired", "disabled"]),
                "uptime": f"{random.randint(0,23)}h {random.randint(0,59)}m",
                "bytes_in": random.randint(10000000, 5000000000),
                "bytes_out": random.randint(5000000, 1000000000),
                "comment": f"Voucher {i+1}",
                "device_id": "default",
                "created_at": datetime.now(timezone.utc).isoformat()
            })
        logger.info("Seeded 25 hotspot users")

    device_count = await db.devices.count_documents({})
    if device_count == 0:
        devices = [
            {"name": "Router-Core-01", "ip_address": "192.168.1.1", "port": 8728, "model": "CCR1036-12G-4S", "status": "online", "cpu_load": 23, "memory_usage": 45, "uptime": "45d 12h 30m"},
            {"name": "Router-Distribution-01", "ip_address": "192.168.1.2", "port": 8728, "model": "RB4011iGS+", "status": "online", "cpu_load": 15, "memory_usage": 32, "uptime": "30d 8h 15m"},
            {"name": "AP-Hotspot-01", "ip_address": "192.168.1.10", "port": 8728, "model": "cAP ac", "status": "online", "cpu_load": 8, "memory_usage": 28, "uptime": "15d 3h 45m"},
            {"name": "Router-Backup-01", "ip_address": "192.168.1.3", "port": 8728, "model": "hEX S", "status": "offline", "cpu_load": 0, "memory_usage": 0, "uptime": "0d 0h 0m"},
        ]
        for d in devices:
            d["id"] = str(uuid.uuid4())
            d["username"] = "admin"
            d["password"] = ""
            d["description"] = f"MikroTik {d['model']}"
            d["created_at"] = datetime.now(timezone.utc).isoformat()
            await db.devices.insert_one(d)
        logger.info("Seeded 4 devices")

# --- Auth Routes ---
@api_router.post("/auth/login")
async def login(data: UserLogin):
    user = await db.admin_users.find_one({"username": data.username}, {"_id": 0})
    if not user or not pwd_context.verify(data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user)
    user_safe = {k: v for k, v in user.items() if k != "password"}
    return {"token": token, "user": user_safe}

@api_router.get("/auth/me")
async def get_me(user=Depends(get_current_user)):
    return {k: v for k, v in user.items() if k != "password"}

# --- Dashboard ---
@api_router.get("/dashboard/stats")
async def get_dashboard_stats(user=Depends(get_current_user)):
    pppoe_total = await db.pppoe_users.count_documents({})
    pppoe_active = await db.pppoe_users.count_documents({"status": "active"})
    hotspot_total = await db.hotspot_users.count_documents({})
    hotspot_active = await db.hotspot_users.count_documents({"status": "active"})
    devices_total = await db.devices.count_documents({})
    devices_online = await db.devices.count_documents({"status": "online"})

    # Mock traffic data for charts
    now = datetime.now(timezone.utc)
    traffic_data = []
    for i in range(24):
        t = now - timedelta(hours=23-i)
        traffic_data.append({
            "time": t.strftime("%H:%M"),
            "download": random.randint(50, 500),
            "upload": random.randint(20, 200),
        })

    # Mock bandwidth by profile
    bandwidth_by_profile = [
        {"name": "10Mbps", "users": random.randint(5, 20), "bandwidth": random.randint(30, 80)},
        {"name": "20Mbps", "users": random.randint(3, 15), "bandwidth": random.randint(40, 120)},
        {"name": "50Mbps", "users": random.randint(2, 10), "bandwidth": random.randint(60, 200)},
        {"name": "100Mbps", "users": random.randint(1, 8), "bandwidth": random.randint(100, 400)},
    ]

    # Mock alerts
    alerts = [
        {"id": "1", "type": "warning", "message": "High CPU on Router-Core-01 (89%)", "time": "5 min ago"},
        {"id": "2", "type": "error", "message": "Router-Backup-01 offline", "time": "15 min ago"},
        {"id": "3", "type": "info", "message": "PPPoE user pppoe_user_12 connected", "time": "30 min ago"},
        {"id": "4", "type": "success", "message": "Firmware update completed on AP-Hotspot-01", "time": "1 hour ago"},
        {"id": "5", "type": "warning", "message": "Memory usage 85% on Router-Distribution-01", "time": "2 hours ago"},
    ]

    return {
        "pppoe": {"total": pppoe_total, "active": pppoe_active},
        "hotspot": {"total": hotspot_total, "active": hotspot_active},
        "devices": {"total": devices_total, "online": devices_online},
        "total_bandwidth": {"download": random.randint(800, 1500), "upload": random.randint(300, 700)},
        "traffic_data": traffic_data,
        "bandwidth_by_profile": bandwidth_by_profile,
        "alerts": alerts,
        "system_health": {
            "cpu": random.randint(15, 85),
            "memory": random.randint(30, 75),
            "disk": random.randint(20, 60),
            "temperature": random.randint(35, 65),
        }
    }

# --- PPPoE Users ---
@api_router.get("/pppoe-users")
async def list_pppoe_users(search: str = "", status: str = "", user=Depends(get_current_user)):
    query = {}
    if search:
        query["$or"] = [
            {"username": {"$regex": search, "$options": "i"}},
            {"ip_address": {"$regex": search, "$options": "i"}},
            {"mac_address": {"$regex": search, "$options": "i"}},
            {"comment": {"$regex": search, "$options": "i"}},
        ]
    if status:
        query["status"] = status
    users = await db.pppoe_users.find(query, {"_id": 0}).to_list(1000)
    return users

@api_router.post("/pppoe-users", status_code=201)
async def create_pppoe_user(data: PPPoEUserCreate, user=Depends(get_current_user)):
    if user["role"] == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot create users")
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["status"] = "active"
    doc["uptime"] = "0d 0h"
    doc["bytes_in"] = 0
    doc["bytes_out"] = 0
    doc["device_id"] = "default"
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.pppoe_users.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api_router.put("/pppoe-users/{user_id}")
async def update_pppoe_user(user_id: str, data: PPPoEUserUpdate, user=Depends(get_current_user)):
    if user["role"] == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot edit users")
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await db.pppoe_users.update_one({"id": user_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    updated = await db.pppoe_users.find_one({"id": user_id}, {"_id": 0})
    return updated

@api_router.delete("/pppoe-users/{user_id}")
async def delete_pppoe_user(user_id: str, user=Depends(require_admin)):
    result = await db.pppoe_users.delete_one({"id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted"}

# --- Hotspot Users ---
@api_router.get("/hotspot-users")
async def list_hotspot_users(search: str = "", status: str = "", user=Depends(get_current_user)):
    query = {}
    if search:
        query["$or"] = [
            {"username": {"$regex": search, "$options": "i"}},
            {"mac_address": {"$regex": search, "$options": "i"}},
            {"comment": {"$regex": search, "$options": "i"}},
        ]
    if status:
        query["status"] = status
    users = await db.hotspot_users.find(query, {"_id": 0}).to_list(1000)
    return users

@api_router.post("/hotspot-users", status_code=201)
async def create_hotspot_user(data: HotspotUserCreate, user=Depends(get_current_user)):
    if user["role"] == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot create users")
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["status"] = "active"
    doc["uptime"] = "0h 0m"
    doc["bytes_in"] = 0
    doc["bytes_out"] = 0
    doc["device_id"] = "default"
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.hotspot_users.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api_router.put("/hotspot-users/{user_id}")
async def update_hotspot_user(user_id: str, data: HotspotUserUpdate, user=Depends(get_current_user)):
    if user["role"] == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot edit users")
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await db.hotspot_users.update_one({"id": user_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    updated = await db.hotspot_users.find_one({"id": user_id}, {"_id": 0})
    return updated

@api_router.delete("/hotspot-users/{user_id}")
async def delete_hotspot_user(user_id: str, user=Depends(require_admin)):
    result = await db.hotspot_users.delete_one({"id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted"}

# --- Devices ---
@api_router.get("/devices")
async def list_devices(user=Depends(get_current_user)):
    devices = await db.devices.find({}, {"_id": 0}).to_list(100)
    return devices

@api_router.post("/devices", status_code=201)
async def create_device(data: DeviceCreate, user=Depends(require_admin)):
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["status"] = "online"
    doc["model"] = "Unknown"
    doc["cpu_load"] = 0
    doc["memory_usage"] = 0
    doc["uptime"] = "0d 0h 0m"
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.devices.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api_router.delete("/devices/{device_id}")
async def delete_device(device_id: str, user=Depends(require_admin)):
    result = await db.devices.delete_one({"id": device_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"message": "Device deleted"}

# --- Reports ---
@api_router.post("/reports/generate")
async def generate_report(data: ReportRequest, user=Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    if data.period == "daily":
        start = now - timedelta(days=1)
        label = "Daily Report"
        intervals = 24
    elif data.period == "weekly":
        start = now - timedelta(weeks=1)
        label = "Weekly Report"
        intervals = 7
    else:
        start = now - timedelta(days=30)
        label = "Monthly Report"
        intervals = 30

    pppoe_total = await db.pppoe_users.count_documents({})
    pppoe_active = await db.pppoe_users.count_documents({"status": "active"})
    hotspot_total = await db.hotspot_users.count_documents({})
    hotspot_active = await db.hotspot_users.count_documents({"status": "active"})
    devices_total = await db.devices.count_documents({})
    devices_online = await db.devices.count_documents({"status": "online"})

    traffic_trend = []
    for i in range(intervals):
        if data.period == "daily":
            t = start + timedelta(hours=i)
            time_label = t.strftime("%H:%M")
        elif data.period == "weekly":
            t = start + timedelta(days=i)
            time_label = t.strftime("%a")
        else:
            t = start + timedelta(days=i)
            time_label = t.strftime("%d/%m")
        traffic_trend.append({
            "time": time_label,
            "download": random.randint(100, 800),
            "upload": random.randint(50, 400),
            "active_users": random.randint(10, 50),
        })

    top_users = []
    pppoe_users = await db.pppoe_users.find({}, {"_id": 0}).sort("bytes_in", -1).to_list(10)
    for u in pppoe_users:
        top_users.append({
            "username": u["username"],
            "type": "PPPoE",
            "download": u.get("bytes_in", 0),
            "upload": u.get("bytes_out", 0),
            "profile": u.get("profile", ""),
        })

    return {
        "label": label,
        "period": data.period,
        "generated_at": now.isoformat(),
        "start_date": start.isoformat(),
        "end_date": now.isoformat(),
        "summary": {
            "pppoe": {"total": pppoe_total, "active": pppoe_active},
            "hotspot": {"total": hotspot_total, "active": hotspot_active},
            "devices": {"total": devices_total, "online": devices_online},
            "avg_bandwidth": {"download": random.randint(500, 1200), "upload": random.randint(200, 600)},
            "peak_bandwidth": {"download": random.randint(1200, 2000), "upload": random.randint(600, 1000)},
        },
        "traffic_trend": traffic_trend,
        "top_users": top_users,
    }

# --- Admin Users ---
@api_router.get("/admin/users")
async def list_admin_users(user=Depends(require_admin)):
    users = await db.admin_users.find({}, {"_id": 0, "password": 0}).to_list(100)
    return users

@api_router.post("/admin/users", status_code=201)
async def create_admin_user(data: UserCreate, user=Depends(require_admin)):
    existing = await db.admin_users.find_one({"username": data.username})
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    if data.role not in ["administrator", "viewer", "user"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    doc = {
        "id": str(uuid.uuid4()),
        "username": data.username,
        "password": pwd_context.hash(data.password),
        "full_name": data.full_name,
        "role": data.role,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.admin_users.insert_one(doc)
    return {k: v for k, v in doc.items() if k not in ["_id", "password"]}

@api_router.put("/admin/users/{user_id}")
async def update_admin_user(user_id: str, data: UserUpdate, user=Depends(require_admin)):
    update_data = {}
    if data.full_name is not None:
        update_data["full_name"] = data.full_name
    if data.role is not None:
        if data.role not in ["administrator", "viewer", "user"]:
            raise HTTPException(status_code=400, detail="Invalid role")
        update_data["role"] = data.role
    if data.password is not None:
        update_data["password"] = pwd_context.hash(data.password)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await db.admin_users.update_one({"id": user_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    updated = await db.admin_users.find_one({"id": user_id}, {"_id": 0, "password": 0})
    return updated

@api_router.delete("/admin/users/{user_id}")
async def delete_admin_user(user_id: str, user=Depends(require_admin)):
    target = await db.admin_users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    await db.admin_users.delete_one({"id": user_id})
    return {"message": "User deleted"}

# --- Health ---
@api_router.get("/health")
async def health():
    return {"status": "ok"}

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
