import os
import uvicorn
import pymongo
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from models import ProductCreate, LicenseCreate, VerifyRequest

from fastapi.responses import PlainTextResponse
import traceback

app = FastAPI(title="NOC Sentinel License Server", version="1.0.0")

@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception):
    return PlainTextResponse(f"Exception: {str(exc)}\n\n{traceback.format_exc()}", status_code=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Load environment variables
load_dotenv()
noc_env_path = os.path.abspath(os.path.join(BASE_DIR, "../../backend/.env"))
if os.path.exists(noc_env_path):
    load_dotenv(noc_env_path)

# DB Setup
mongo_uri = os.environ.get("MONGO_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017/"
db_name = os.environ.get("MONGO_DB_NAME") or os.environ.get("DB_NAME", "nocsentinel")
client = pymongo.MongoClient(mongo_uri)
db = client[db_name]

c_products = db["license_products"]
c_licenses = db["license_keys"]
c_logs = db["license_logs"]

# ── FRONTEND VIEWS ────────────────────────────────────────────────────────────

@app.get("/")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard")
async def dashboard_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ── API ROUTES ────────────────────────────────────────────────────────────────

@app.post("/api/v1/products")
def create_product(prod: ProductCreate):
    doc = prod.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    c_products.insert_one(doc)
    doc.pop("_id", None)
    return {"message": "Product created", "product": doc}

@app.get("/api/v1/products")
def get_products():
    return list(c_products.find({}, {"_id": 0}))

@app.post("/api/v1/licenses")
def generate_license(req: LicenseCreate):
    product = c_products.find_one({"id": req.product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    # Generate Key e.g NOC-ABCD-1234-WXYZ
    key = "NOC-" + "-".join([secrets.token_hex(2).upper() for _ in range(3)])
    
    # Calculate expiry
    now = datetime.now(timezone.utc)
    if product["type"] == "lifetime":
        expires_at = (now + timedelta(days=36500)).isoformat()
    else:
        expires_at = (now + timedelta(days=30 * product.get("duration_months", 1))).isoformat()

    doc = {
        "id": str(uuid.uuid4()),
        "license_key": key,
        "product_id": product["id"],
        "customer_name": req.customer_name,
        "type": product["type"],
        "max_devices": req.max_devices,
        "hardware_ids": [],
        "created_at": now.isoformat(),
        "expires_at": expires_at,
        "is_active": True,
        "notes": req.notes
    }
    c_licenses.insert_one(doc)
    doc.pop("_id", None)
    return {"message": "License generated", "license": doc}

@app.get("/api/v1/licenses")
def get_licenses():
    return list(c_licenses.find({}, {"_id": 0}).sort("created_at", -1))

@app.post("/api/v1/license/verify")
def verify_license(req: VerifyRequest):
    now_iso = datetime.now(timezone.utc).isoformat()
    def log_activity(status):
        c_logs.insert_one({
            "id": str(uuid.uuid4()),
            "license_key": req.license_key,
            "hardware_id": req.hardware_id,
            "ip_address": req.ip_address,
            "status": status,
            "timestamp": now_iso
        })
        
    license_doc = c_licenses.find_one({"license_key": req.license_key})
    
    if not license_doc:
        log_activity("Cracked")
        raise HTTPException(status_code=403, detail="Invalid License Key")
        
    if not license_doc.get("is_active", True):
        log_activity("Inactive")
        raise HTTPException(status_code=403, detail="License is suspended or inactive")
        
    if license_doc["expires_at"] < now_iso:
        log_activity("Expired")
        raise HTTPException(status_code=403, detail="License has expired")

    # Hardware ID Verification
    hw_ids = license_doc.get("hardware_ids", [])
    if not hw_ids:
        # First use, bind hardware ID
        c_licenses.update_one({"id": license_doc["id"]}, {"$push": {"hardware_ids": req.hardware_id}})
    elif req.hardware_id not in hw_ids:
        if len(hw_ids) < license_doc.get("max_devices", 1):
            c_licenses.update_one({"id": license_doc["id"]}, {"$push": {"hardware_ids": req.hardware_id}})
        else:
            log_activity("Cloned")
            raise HTTPException(status_code=403, detail="License is already bound to maximum number of devices (Cloned detected)")

    log_activity("Valid")
    
    return {
        "status": "valid",
        "type": license_doc.get("type"),
        "customer": license_doc.get("customer_name"),
        "expires_at": license_doc.get("expires_at"),
        "max_devices": license_doc.get("max_devices")
    }

@app.get("/api/v1/dashboard/stats")
def get_dashboard_stats():
    now_iso = datetime.now(timezone.utc).isoformat()
    total = c_licenses.count_documents({})
    active = c_licenses.count_documents({"is_active": True, "expires_at": {"$gt": now_iso}})
    inactive = c_licenses.count_documents({"$or": [{"is_active": False}, {"expires_at": {"$lt": now_iso}}]})
    cracked = c_logs.count_documents({"status": "Cracked"})
    cloned = c_logs.count_documents({"status": "Cloned"})
    
    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "cracked": cracked,
        "cloned": cloned
    }

@app.get("/api/v1/monitoring_logs")
def get_logs(limit: int = 50):
    logs = list(c_logs.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit))
    return logs

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=1744, reload=True)
