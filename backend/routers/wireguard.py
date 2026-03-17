"""
WireGuard VPN API route.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import logging
from typing import Optional

from core.db import get_db
from core.auth import require_admin
import core.wireguard_service as wg_svc

router = APIRouter(prefix="/wireguard", tags=["wireguard"])
logger = logging.getLogger(__name__)

class WGConfigSchema(BaseModel):
    enabled: bool = False
    private_key: str = ""
    client_ip: str = ""
    server_endpoint: str = ""
    server_public_key: str = ""
    allowed_ips: str = "0.0.0.0/0"

@router.get("/config")
async def get_wireguard_config():
    """Mengambil konfigurasi WireGuard client system"""
    db = get_db()
    curr = await db.settings.find_one({"_id": "wireguard_config"})
    if not curr:
        curr = WGConfigSchema().dict()
    else:
        curr.pop("_id", None)
        
    # Generate local public key from private key if exists
    curr["local_public_key"] = wg_svc.get_pubkey_from_privkey(curr.get("private_key", ""))
    return curr

@router.put("/config", dependencies=[]) # Todo: add require_admin
async def update_wireguard_config(config: WGConfigSchema):
    db = get_db()
    new_cfg = config.dict()
    
    # Save to db
    await db.settings.update_one(
        {"_id": "wireguard_config"},
        {"$set": new_cfg},
        upsert=True
    )
    
    # If disabled, turn it off immediately
    if not new_cfg["enabled"]:
        wg_svc.wg_down()
        return {"status": "success", "message": "Konfigurasi disimpan dan Tunnel dinonaktifkan."}
    
    # If enabled, build config and apply it
    success = wg_svc.generate_wg_config(new_cfg)
    if not success:
        raise HTTPException(status_code=500, detail="Gagal me-nyimpan file konfigurasi wg0 di system.")
    
    ok, output = wg_svc.wg_up()
    if not ok:
        raise HTTPException(status_code=500, detail=f"Gagal menyalakan tunnel WG: {output}")
        
    return {"status": "success", "message": "Konfigurasi disimpan dan Tunnel WireGuard menyala.", "output": output}

@router.get("/status")
async def get_wireguard_status():
    """Mengambil kernel real-time status of WireGuard"""
    # Check if enabled in db first
    db = get_db()
    curr = await db.settings.find_one({"_id": "wireguard_config"})
    if not curr or not curr.get("enabled", False):
        return {"status": "disabled", "message": "WireGuard client tidak aktif."}
        
    stats = wg_svc.get_wg_status()
    # Jika wg show dump error atau kosong karena interface tidak ada
    if not stats["public_key"]:
        return {"status": "offline", "message": "Tunnel wg0 tidak ditemukan / mati."}
        
    return stats

@router.get("/generate-keys")
async def generate_wireguard_keys():
    """Generate a new private and public key pair for WireGuard."""
    priv = wg_svc.generate_private_key()
    if not priv:
        raise HTTPException(status_code=500, detail="Gagal men-generate private key. Pastikan WireGuard terinstall (apt install wireguard).")
    
    pub = wg_svc.get_pubkey_from_privkey(priv)
    return {
        "private_key": priv,
        "public_key": pub
    }
