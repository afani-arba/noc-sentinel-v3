import os
import uvicorn
import pymongo
import uuid
import secrets
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from models import ProductCreate, LicenseCreate, VerifyRequest

app = FastAPI(title="NOC Sentinel License Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# DB Setup
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["noc_license_db"]

# ── FRONTEND VIEWS ────────────────────────────────────────────────────────────

@app.get("/")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard")
async def dashboard_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ── API ROUTES ────────────────────────────────────────────────────────────────

@app.post("/api/v1/products")
async def create_product(prod: ProductCreate):
    doc = prod.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    db.products.insert_one(doc)
    return {"message": "Product created", "product": doc}

@app.get("/api/v1/products")
async def get_products():
    return list(db.products.find({}, {"_id": 0}))

@app.post("/api/v1/licenses")
async def generate_license(req: LicenseCreate):
    product = db.products.find_one({"id": req.product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    # Generate Key e.g NOC-ABCD-1234-WXYZ
    key = "NOC-" + "-".join([secrets.token_hex(2).upper() for _ in range(3)])
    
    # Calculate expiry
    now = datetime.now(timezone.utc)
    if product["type"] == "lifetime":
        expires_at = (now + relativedelta(years=100)).isoformat()
    else:
        expires_at = (now + relativedelta(months=product.get("duration_months", 1))).isoformat()

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
    db.licenses.insert_one(doc)
    return {"message": "License generated", "license": doc}

@app.get("/api/v1/licenses")
async def get_licenses():
    return list(db.licenses.find({}, {"_id": 0}).sort("created_at", -1))

@app.post("/api/v1/license/verify")
async def verify_license(req: VerifyRequest):
    now_iso = datetime.now(timezone.utc).isoformat()
    def log_activity(status):
        db.monitoring_logs.insert_one({
            "id": str(uuid.uuid4()),
            "license_key": req.license_key,
            "hardware_id": req.hardware_id,
            "ip_address": req.ip_address,
            "status": status,
            "timestamp": now_iso
        })
        
    license_doc = db.licenses.find_one({"license_key": req.license_key})
    
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
        db.licenses.update_one({"id": license_doc["id"]}, {"$push": {"hardware_ids": req.hardware_id}})
    elif req.hardware_id not in hw_ids:
        if len(hw_ids) < license_doc.get("max_devices", 1):
            db.licenses.update_one({"id": license_doc["id"]}, {"$push": {"hardware_ids": req.hardware_id}})
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
async def get_dashboard_stats():
    now_iso = datetime.now(timezone.utc).isoformat()
    total = db.licenses.count_documents({})
    active = db.licenses.count_documents({"is_active": True, "expires_at": {"$gt": now_iso}})
    inactive = db.licenses.count_documents({"$or": [{"is_active": False}, {"expires_at": {"$lt": now_iso}}]})
    cracked = db.monitoring_logs.count_documents({"status": "Cracked"})
    cloned = db.monitoring_logs.count_documents({"status": "Cloned"})
    
    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "cracked": cracked,
        "cloned": cloned
    }

@app.get("/api/v1/monitoring_logs")
async def get_logs(limit: int = 50):
    logs = list(db.monitoring_logs.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit))
    return logs

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=1777, reload=True)
