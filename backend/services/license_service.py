import asyncio
import uuid
import hashlib
import httpx
import logging
from datetime import datetime, timezone
from core.db import get_db

logger = logging.getLogger(__name__)

LICENSE_SERVER_URL = "http://103.217.217.36:1777"

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
                await db.system_settings.update_one(
                    {"_id": "license_status"},
                    {"$set": {
                        "status": "valid",
                        "type": data.get("type"),
                        "customer": data.get("customer"),
                        "expires_at": data.get("expires_at"),
                        "hardware_id": hw_id,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }},
                    upsert=True
                )
                return True
            else:
                err = res.json().get("detail", "Invalid License")
                await db.system_settings.update_one(
                    {"_id": "license_status"},
                    {"$set": {"status": "invalid", "message": err, "updated_at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True
                )
                return False
    except Exception as e:
        logger.warning(f"Failed to connect to License Server: {e}. Running on grace period.")
        # Grace period: if it was valid before, keep it valid until expires_at
        status_doc = await db.system_settings.find_one({"_id": "license_status"})
        if status_doc and status_doc.get("status") == "valid":
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
