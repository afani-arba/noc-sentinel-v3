import asyncio
import uuid
import hashlib
import httpx
import os
import logging
from datetime import datetime, timezone
from core.db import get_db

logger = logging.getLogger(__name__)

LICENSE_SERVER_URL = os.environ.get("LICENSE_SERVER_URL", "http://103.217.217.36:1744").rstrip('/')

def get_hardware_id():
    """Generate a unique hardware fingerprint using MAC address / node."""
    node = uuid.getnode()
    return "HW-" + hashlib.sha256(str(node).encode()).hexdigest()[:12].upper()

async def verify_license_now():
    """Check license right now and update DB."""
    db = get_db()
    
    # Get current key
    doc = await db.system_settings.find_one({"_id": "license"})
    if not doc or not doc.get("license_key"):
        await db.system_settings.update_one(
            {"_id": "license_status"},
            {"$set": {"status": "unlicensed", "message": "No License Key found", "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True
        )
        return False

    key = doc.get("license_key")
    hw_id = get_hardware_id()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{LICENSE_SERVER_URL}/api/v1/license/verify",
                json={"license_key": key, "hardware_id": hw_id, "ip_address": "auto"}
            )
            
            if res.status_code == 200:
                data = res.json()
                now_str = datetime.now(timezone.utc).isoformat()
                await db.system_settings.update_one(
                    {"_id": "license_status"},
                    {"$set": {
                        "status": "valid",
                        "type": data.get("type"),
                        "customer": data.get("customer"),
                        "expires_at": data.get("expires_at"),
                        "hardware_id": hw_id,
                        "last_online_check": now_str,
                        "last_seen_time": now_str,
                        "updated_at": now_str
                    }},
                    upsert=True
                )
                return True
            else:
                err = res.json().get("detail", "Invalid License")
                now_str = datetime.now(timezone.utc).isoformat()
                await db.system_settings.update_one(
                    {"_id": "license_status"},
                    {
                        "$set": {"status": "invalid", "message": err, "updated_at": now_str},
                        # Don't update last_seen_time here fully, just minimum needed
                    },
                    upsert=True
                )
                return False
    except Exception as e:
        logger.warning(f"Failed to connect to License Server: {e}. Running on grace period.")
        # Grace period fallback with Anti-Tampering
        status_doc = await db.system_settings.find_one({"_id": "license_status"})
        
        if status_doc and status_doc.get("status") == "valid":
            now_str = datetime.now(timezone.utc).isoformat()
            last_seen = status_doc.get("last_seen_time", "2000-01-01T00:00:00")
            last_online = status_doc.get("last_online_check", "2000-01-01T00:00:00")
            
            # 1. Anti-Time Tampering (Clock rewind detection)
            if now_str < last_seen:
                logger.error("SYSTEM CLOCK TAMPERING DETECTED! Time went backwards. Locking license.")
                await db.system_settings.update_one(
                    {"_id": "license_status"},
                    {"$set": {
                        "status": "invalid", 
                        "message": "Manipulation of OS Clock detected. Internet required to verify license.",
                        "last_seen_time": now_str
                    }}
                )
                return False
                
            # 2. Max Offline Tolerance (Max 3 Days allowed without internet)
            try:
                last_online_dt = datetime.fromisoformat(last_online.replace('Z', '+00:00'))
                diff_days = (datetime.now(timezone.utc) - last_online_dt).days
                if diff_days > 3:
                    logger.error(f"Maximum offline grace period exceeded ({diff_days} days). Locking license.")
                    await db.system_settings.update_one(
                        {"_id": "license_status"},
                        {"$set": {
                            "status": "invalid", 
                            "message": f"Offline grace period exceeded ({diff_days} / 3 days maximum). Please connect to the internet.",
                            "last_seen_time": now_str
                        }}
                    )
                    return False
            except Exception as dt_err:
                logger.warning(f"Date parsing error in grace period: {dt_err}")
                
            # Update last_seen_time to progress forward
            await db.system_settings.update_one(
                {"_id": "license_status"},
                {"$set": {"last_seen_time": now_str}}
            )
            return True
            
        return False

async def license_check_loop():
    """Background task to periodically verify license."""
    logger.info(f"License verification loop started. HW ID: {get_hardware_id()}")
    # Intial check on boot
    await asyncio.sleep(5)
    await verify_license_now()
    
    while True:
        await asyncio.sleep(3600)  # Check every hour
        await verify_license_now()
