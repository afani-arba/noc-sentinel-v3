"""
Hotspot users router: list, create, update, delete via MikroTik API.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from core.db import get_db
from core.auth import get_current_user, require_admin, require_write
from mikrotik_api import get_api_client

router = APIRouter(tags=["hotspot"])


class HotspotUserCreate(BaseModel):
    name: str
    password: str
    profile: str = "default"
    server: str = "all"
    comment: str = ""
    price: Optional[str] = "0"
    validity: Optional[str] = ""

class HotspotUserBatchCreate(BaseModel):
    users: list[HotspotUserCreate]

class HotspotUserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    profile: Optional[str] = None
    server: Optional[str] = None
    comment: Optional[str] = None
    disabled: Optional[str] = None


async def _get_mt_api(device_id: str):
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    return get_api_client(device), device


@router.get("/hotspot-users")
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

@router.get("/hotspot-vouchers")
async def list_hotspot_vouchers(device_id: str = "", search: str = "", user=Depends(get_current_user)):
    db = get_db()
    query = {}
    if device_id:
        query["device_id"] = device_id
    if search:
        query["username"] = {"$regex": search, "$options": "i"}
        
    vouchers = await db.hotspot_vouchers.find(query).to_list(1000)
    for v in vouchers:
        v["_id"] = str(v["_id"])
    return vouchers

@router.delete("/hotspot-vouchers/{vid}")
async def delete_hotspot_voucher(vid: str, user=Depends(require_write)):
    db = get_db()
    res = await db.hotspot_vouchers.delete_one({"id": vid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Voucher not found")
    return {"message": "Deleted"}


@router.post("/hotspot-users", status_code=201)
async def create_hotspot_user(device_id: str, data: HotspotUserCreate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    # Remove custom fields before sending to MT
    body = {k: v for k, v in data.model_dump().items() if v and k not in ("price", "validity")}
    try:
        return await mt.create_hotspot_user(body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")

from datetime import datetime
import uuid

@router.post("/hotspot-users/batch", status_code=201)
async def create_hotspot_users_batch(device_id: str, data: HotspotUserBatchCreate, user=Depends(require_write)):
    # Batch creation using Internal RADIUS
    # Instead of sending to MikroTik, we just save them locally in MongoDB
    db = get_db()
    created = 0
    errors = []
    
    docs = []
    for u in data.users:
        doc = {
            "id": str(uuid.uuid4()),
            "username": u.name,
            "password": u.password,
            "profile": u.profile,
            "server": u.server,
            "price": u.price,
            "validity": u.validity,
            "status": "new",
            "device_id": device_id,
            "created_at": datetime.now().isoformat()
        }
        docs.append(doc)
        
    if docs:
        try:
            await db.hotspot_vouchers.insert_many(docs)
            created = len(docs)
        except Exception as e:
            raise HTTPException(500, f"Database error: {e}")
            
    return {"message": f"Successfully created {created} vouchers in Database", "errors": None}


@router.put("/hotspot-users/{mt_id}")
async def update_hotspot_user(mt_id: str, device_id: str, data: HotspotUserUpdate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    body = {k: v for k, v in data.model_dump().items() if v is not None}
    try:
        return await mt.update_hotspot_user(mt_id, body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.delete("/hotspot-users/{mt_id}")
async def delete_hotspot_user(mt_id: str, device_id: str, user=Depends(require_admin)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.delete_hotspot_user(mt_id)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.get("/hotspot-active")
async def list_hotspot_active(device_id: str, user=Depends(get_current_user)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.list_hotspot_active()
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.get("/hotspot-profiles")
async def list_hotspot_profiles(device_id: str, user=Depends(get_current_user)):
    """List Hotspot user profiles from MikroTik (for use in create/edit user forms)."""
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt_api(device_id)
        profiles = await mt.list_hotspot_profiles()
        return [
            {"name": p.get("name", ""), "rate_limit": p.get("rate-limit", p.get("rate_limit", "")), "shared_users": p.get("shared-users", ""), "comment": p.get("comment", "")}
            for p in profiles if p.get("name")
        ]
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.get("/hotspot-servers")
async def list_hotspot_servers(device_id: str, user=Depends(get_current_user)):
    """List Hotspot servers from MikroTik."""
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt_api(device_id)
        servers = await mt.list_hotspot_servers()
        return [
            {"name": s.get("name", ""), "interface": s.get("interface", "")}
            for s in servers if s.get("name")
        ]
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")
