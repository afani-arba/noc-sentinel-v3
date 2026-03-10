"""
GenieACS router: endpoints for managing TR-069 CPE devices via GenieACS NBI.
All endpoints prefixed with /genieacs
"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from core.auth import get_current_user, require_admin
from services import genieacs_service as svc

router = APIRouter(prefix="/genieacs", tags=["genieacs"])
logger = logging.getLogger(__name__)


def _err(e: Exception, default="GenieACS error"):
    msg = str(e)
    if "Connection refused" in msg or "Failed to establish" in msg:
        raise HTTPException(503, "Tidak dapat terhubung ke GenieACS. Pastikan GENIEACS_URL benar dan server GenieACS aktif.")
    if "401" in msg or "Unauthorized" in msg:
        raise HTTPException(401, "Autentikasi GenieACS gagal. Periksa GENIEACS_USERNAME dan GENIEACS_PASSWORD.")
    if "404" in msg:
        raise HTTPException(404, "Device tidak ditemukan di GenieACS.")
    raise HTTPException(502, f"{default}: {msg}")


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(user=Depends(get_current_user)):
    """Overall GenieACS stats: total, online, offline, faults."""
    try:
        return await asyncio.to_thread(svc.get_stats)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get stats")


# ── Devices ───────────────────────────────────────────────────────────────────

@router.get("/devices")
async def list_devices(
    limit: int = Query(200, le=1000),
    search: str = Query(""),
    model: str = Query(""),
    user=Depends(get_current_user),
):
    """List CPE devices with optional search/filter."""
    try:
        devices = await asyncio.to_thread(svc.get_devices, limit, search, model)
        return _normalize_devices(devices)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to list devices")


@router.get("/devices/{device_id:path}")
async def get_device(device_id: str, user=Depends(get_current_user)):
    """Get detailed info + parameter tree for one device."""
    try:
        return await asyncio.to_thread(svc.get_device, device_id)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get device")


# ── Actions ───────────────────────────────────────────────────────────────────

@router.post("/devices/{device_id:path}/reboot")
async def reboot_device(device_id: str, user=Depends(require_admin)):
    """Send reboot command to CPE."""
    try:
        result = await asyncio.to_thread(svc.reboot_device, device_id)
        return {"message": "Perintah reboot dikirim ke device", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Reboot failed")


@router.post("/devices/{device_id:path}/factory-reset")
async def factory_reset(device_id: str, user=Depends(require_admin)):
    """Send factory reset to CPE."""
    try:
        result = await asyncio.to_thread(svc.factory_reset_device, device_id)
        return {"message": "Perintah factory reset dikirim", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Factory reset failed")


@router.post("/devices/{device_id:path}/refresh")
async def refresh_device(device_id: str, user=Depends(require_admin)):
    """Refresh all parameters from CPE."""
    try:
        result = await asyncio.to_thread(svc.refresh_device, device_id)
        return {"message": "Refresh parameter dikirim", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Refresh failed")


@router.post("/devices/{device_id:path}/set-parameter")
async def set_param(device_id: str, body: dict, user=Depends(require_admin)):
    """Set a specific TR-069 parameter on device."""
    name = body.get("name")
    value = body.get("value", "")
    type_ = body.get("type", "xsd:string")
    if not name:
        raise HTTPException(400, "Parameter name wajib diisi")
    try:
        result = await asyncio.to_thread(svc.set_parameter, device_id, name, value, type_)
        return {"message": f"Parameter {name} berhasil diset", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Set parameter failed")


# ── Faults ────────────────────────────────────────────────────────────────────

@router.get("/faults")
async def list_faults(limit: int = Query(100), user=Depends(get_current_user)):
    try:
        return await asyncio.to_thread(svc.get_faults, limit)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get faults")


@router.delete("/faults/{fault_id:path}")
async def delete_fault(fault_id: str, user=Depends(require_admin)):
    try:
        return await asyncio.to_thread(svc.delete_fault, fault_id)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to delete fault")


# ── Presets & Files ───────────────────────────────────────────────────────────

@router.get("/presets")
async def list_presets(user=Depends(get_current_user)):
    try:
        return await asyncio.to_thread(svc.get_presets)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get presets")


@router.get("/files")
async def list_files(user=Depends(get_current_user)):
    try:
        return await asyncio.to_thread(svc.get_files)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get files")


# ── Test Connection ───────────────────────────────────────────────────────────

@router.get("/test-connection")
async def test_connection(user=Depends(require_admin)):
    """Test connectivity to GenieACS NBI."""
    from services.genieacs_service import GENIEACS_URL
    try:
        stats = await asyncio.to_thread(svc.get_stats)
        return {
            "success": True,
            "url": GENIEACS_URL,
            "message": f"Terhubung! Total CPE: {stats['total']}, Online: {stats['online']}",
            "stats": stats,
        }
    except Exception as e:
        return {"success": False, "url": GENIEACS_URL, "error": str(e)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_devices(devices: list) -> list:
    """Extract key fields from raw GenieACS device objects for list view."""
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    result = []
    for d in devices:
        last_inform = d.get("_lastInform", "")
        is_online = False
        if last_inform:
            try:
                dt = datetime.fromisoformat(last_inform.replace("Z", "+00:00"))
                is_online = dt > cutoff
            except Exception:
                pass

        igd = d.get("InternetGatewayDevice", {})
        dev_info = igd.get("DeviceInfo", {})
        wan = (
            igd.get("WANDevice", {})
               .get("1", {})
               .get("WANConnectionDevice", {})
               .get("1", {})
               .get("WANIPConnection", {})
               .get("1", {})
        )

        result.append({
            "id": d.get("_id", ""),
            "manufacturer": _val(dev_info, "Manufacturer"),
            "model": _val(dev_info, "ModelName"),
            "serial": _val(dev_info, "SerialNumber"),
            "firmware": _val(dev_info, "SoftwareVersion"),
            "uptime": _val(dev_info, "UpTime"),
            "ip": _val(wan, "ExternalIPAddress"),
            "last_inform": last_inform,
            "online": is_online,
            "registered": d.get("_registered", ""),
        })
    return result


def _val(obj: dict, key: str) -> str:
    """Extract ._value from GenieACS parameter dict."""
    if not obj or key not in obj:
        return ""
    item = obj[key]
    if isinstance(item, dict):
        return str(item.get("_value", ""))
    return str(item)
