"""
GenieACS NBI (Northbound Interface) service.
Connects to GenieACS REST API at port 7557 to manage TR-069 CPE devices.

Configure via .env:
  GENIEACS_URL=http://10.x.x.x:7557
  GENIEACS_USERNAME=admin
  GENIEACS_PASSWORD=secret
"""
import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

GENIEACS_URL = os.environ.get("GENIEACS_URL", "http://localhost:7557").rstrip("/")
GENIEACS_USER = os.environ.get("GENIEACS_USERNAME", "")
GENIEACS_PASS = os.environ.get("GENIEACS_PASSWORD", "")
TIMEOUT = 20


def _auth() -> Optional[tuple]:
    if GENIEACS_USER:
        return (GENIEACS_USER, GENIEACS_PASS)
    return None


def _get(path: str, params: dict = None) -> any:
    url = f"{GENIEACS_URL}/{path.lstrip('/')}"
    resp = requests.get(url, params=params, auth=_auth(), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict = None) -> any:
    url = f"{GENIEACS_URL}/{path.lstrip('/')}"
    resp = requests.post(url, json=data, auth=_auth(), timeout=TIMEOUT)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code}


def _delete(path: str) -> any:
    url = f"{GENIEACS_URL}/{path.lstrip('/')}"
    resp = requests.delete(url, auth=_auth(), timeout=TIMEOUT)
    resp.raise_for_status()
    return {"success": True}


# ── Devices ───────────────────────────────────────────────────────────────────

def get_devices(limit: int = 200, search: str = "", model: str = "") -> list:
    """
    List all CPE devices from GenieACS.
    GenieACS query uses MongoDB-style queries via 'query' param.
    """
    params = {"limit": limit}
    if search:
        # Search by deviceId, serial, model, or IP (use $regex on common fields)
        params["query"] = (
            '{"$or":['
            f'{{"_id":{{"$regex":"{search}","$options":"i"}}}},'
            f'{{"InternetGatewayDevice.DeviceInfo.ModelName._value":{{"$regex":"{search}","$options":"i"}}}},'
            f'{{"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1.ExternalIPAddress._value":{{"$regex":"{search}","$options":"i"}}}}'
            ']}'
        )
    elif model:
        params["query"] = f'{{"InternetGatewayDevice.DeviceInfo.ModelName._value":{{"$regex":"{model}","$options":"i"}}}}'
    return _get("/devices", params)


def get_device(device_id: str) -> dict:
    """Get full parameter tree of one device."""
    return _get(f"/devices/{requests.utils.quote(device_id, safe='')}")


def get_device_summary(device_id: str) -> dict:
    """Get key info fields for a device (lighter than full tree)."""
    fields = [
        "_id", "_lastInform", "_registered",
        "InternetGatewayDevice.DeviceInfo.Manufacturer._value",
        "InternetGatewayDevice.DeviceInfo.ModelName._value",
        "InternetGatewayDevice.DeviceInfo.SerialNumber._value",
        "InternetGatewayDevice.DeviceInfo.SoftwareVersion._value",
        "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1.ExternalIPAddress._value",
        "InternetGatewayDevice.DeviceInfo.UpTime._value",
        "VirtualParameters.Tag._value",
    ]
    params = {
        "projection": ",".join(fields),
        "limit": 1,
        "query": f'{{"_id":"{device_id}"}}',
    }
    results = _get("/devices", params)
    return results[0] if results else {}


def reboot_device(device_id: str) -> dict:
    """Send reboot task to device."""
    return _post(f"/devices/{requests.utils.quote(device_id, safe='')}/tasks?timeout=3000&connection_request", {"name": "reboot"})


def factory_reset_device(device_id: str) -> dict:
    """Send factory reset task to device."""
    return _post(f"/devices/{requests.utils.quote(device_id, safe='')}/tasks?timeout=3000&connection_request", {"name": "factoryReset"})


def refresh_device(device_id: str) -> dict:
    """Send refreshObject task to refresh all parameters."""
    return _post(
        f"/devices/{requests.utils.quote(device_id, safe='')}/tasks?timeout=3000&connection_request",
        {"name": "refreshObject", "objectName": ""}
    )


def set_parameter(device_id: str, param_name: str, param_value: str, param_type: str = "xsd:string") -> dict:
    """Set a TR-069 parameter on device."""
    return _post(
        f"/devices/{requests.utils.quote(device_id, safe='')}/tasks?timeout=3000&connection_request",
        {
            "name": "setParameterValues",
            "parameterValues": [[param_name, param_value, param_type]]
        }
    )


# ── Faults ────────────────────────────────────────────────────────────────────

def get_faults(limit: int = 100) -> list:
    """List recent faults across all devices."""
    return _get("/faults", {"limit": limit})


def delete_fault(fault_id: str) -> dict:
    """Delete/resolve a fault."""
    return _delete(f"/faults/{fault_id}")


# ── Tasks ─────────────────────────────────────────────────────────────────────

def get_tasks(device_id: str) -> list:
    """List pending tasks for a device."""
    params = {"query": f'{{"device":"{device_id}"}}'}
    return _get("/tasks", params)


# ── Presets & Files ───────────────────────────────────────────────────────────

def get_presets() -> list:
    """List all provisioning presets."""
    return _get("/presets")


def get_files() -> list:
    """List firmware/config files uploaded to GenieACS."""
    return _get("/files")


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    """
    Return overall stats: total devices, online count, faults count.
    'Online' = lastInform within last 15 minutes.
    """
    try:
        all_devices = _get("/devices", {"limit": 5000, "projection": "_id,_lastInform"})
        total = len(all_devices)

        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)

        online = 0
        for d in all_devices:
            last = d.get("_lastInform")
            if last:
                try:
                    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    if last_dt > cutoff:
                        online += 1
                except Exception:
                    pass

        faults = _get("/faults", {"limit": 1000, "projection": "_id"})
        return {"total": total, "online": online, "offline": total - online, "faults": len(faults)}
    except Exception as e:
        logger.warning(f"GenieACS stats error: {e}")
        return {"total": 0, "online": 0, "offline": 0, "faults": 0}
