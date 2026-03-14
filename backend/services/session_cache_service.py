"""
Session Cache Service — PPPoE & Hotspot Active Count Background Fetcher.

Strategi:
- ROS7 (api_mode="rest"): fetch langsung via REST API — non-blocking, cepat
- ROS6 (api_mode="api"): SKIP — data sudah diupdate oleh polling.py setiap 30 detik
  menggunakan routeros_api (synchronous/threading). Session_cache tidak perlu re-fetch
  karena polling sudah menyimpan pppoe_active/hotspot_active ke DB.

Wallboard membaca nilai ini dari DB → tidak ada flicker/hilang-timbul.
Interval default: 300 detik (5 menit). Ubah via env SESSION_CACHE_INTERVAL.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from core.db import get_db
from mikrotik_api import get_api_client

logger = logging.getLogger(__name__)

SESSION_CACHE_INTERVAL = int(os.environ.get("SESSION_CACHE_INTERVAL", "300"))
SESSION_FETCH_TIMEOUT  = 20   # detik — untuk REST API ROS7
SESSION_MAX_CONCURRENT = 15   # concurrent untuk ROS7 (REST - lebih ringan)


async def _fetch_rest_device(device: dict) -> tuple[str, int, int]:
    """
    Fetch PPPoE + Hotspot count via REST API untuk device ROS7.
    Returns (device_id, pppoe_count, hotspot_count).
    -1 = gagal → pertahankan nilai DB lama.
    """
    dev_id   = device.get("id", "")
    dev_name = device.get("name", dev_id)

    try:
        mt = get_api_client(device)

        pppoe_count   = 0
        hotspot_count = 0

        try:
            pppoe_list = await asyncio.wait_for(
                mt.list_pppoe_active(), timeout=SESSION_FETCH_TIMEOUT
            )
            pppoe_count = len(pppoe_list) if isinstance(pppoe_list, list) else 0
        except asyncio.TimeoutError:
            logger.warning(f"[session_cache] Timeout PPPoE {dev_name}")
            pppoe_count = -1
        except NotImplementedError:
            pass
        except Exception as e:
            logger.debug(f"[session_cache] PPPoE gagal {dev_name}: {e}")

        try:
            hs_list = await asyncio.wait_for(
                mt.list_hotspot_active(), timeout=SESSION_FETCH_TIMEOUT
            )
            hotspot_count = len(hs_list) if isinstance(hs_list, list) else 0
        except asyncio.TimeoutError:
            logger.warning(f"[session_cache] Timeout Hotspot {dev_name}")
            hotspot_count = -1
        except NotImplementedError:
            pass
        except Exception as e:
            logger.debug(f"[session_cache] Hotspot gagal {dev_name}: {e}")

        logger.info(f"[session_cache] {dev_name}: pppoe={pppoe_count} hs={hotspot_count}")
        return dev_id, pppoe_count, hotspot_count

    except Exception as e:
        logger.warning(f"[session_cache] Error {dev_name}: {e}")
        return dev_id, -1, -1


async def refresh_session_cache():
    """
    Fetch session counts dari device ROS7 (REST API) online secara paralel.
    ROS6 device di-skip — polling.py sudah handle mereka setiap 30 detik.
    """
    db = get_db()
    # Hanya ambil device online dengan api_mode REST (ROS7)
    # ROS6 (api_mode="api") tidak di-fetch — sudah dihandle polling.py
    all_online = await db.devices.find(
        {"status": "online"},
        {"_id": 0}
    ).to_list(500)

    # Filter: hanya REST API devices
    rest_devices = [d for d in all_online if d.get("api_mode", "rest") != "api"]
    ros6_devices = [d for d in all_online if d.get("api_mode", "rest") == "api"]

    if not all_online:
        logger.info("[session_cache] Tidak ada device online.")
        return

    logger.info(
        f"[session_cache] Refresh: {len(rest_devices)} REST (akan di-fetch), "
        f"{len(ros6_devices)} ROS6 (skip - dihandle polling.py)"
    )

    if not rest_devices:
        return

    sem = asyncio.Semaphore(SESSION_MAX_CONCURRENT)

    async def throttled(device):
        async with sem:
            return await _fetch_rest_device(device)

    results = await asyncio.gather(
        *[throttled(d) for d in rest_devices],
        return_exceptions=True,
    )

    updated = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()

    for result in results:
        if not isinstance(result, tuple) or len(result) != 3:
            skipped += 1
            continue

        dev_id, pppoe, hotspot = result
        if not dev_id:
            skipped += 1
            continue

        set_fields: dict = {"session_cache_at": now}
        if pppoe >= 0:
            set_fields["pppoe_active"] = pppoe
        if hotspot >= 0:
            set_fields["hotspot_active"] = hotspot

        if len(set_fields) <= 1:
            skipped += 1
            continue

        await db.devices.update_one({"id": dev_id}, {"$set": set_fields})
        updated += 1

    logger.info(
        f"[session_cache] Selesai: {updated} REST diupdate, {skipped} skip. "
        f"Interval berikutnya {SESSION_CACHE_INTERVAL}s."
    )


async def session_cache_loop():
    """Background loop: refresh setiap SESSION_CACHE_INTERVAL detik."""
    logger.info(
        f"[session_cache] Service dimulai (REST-only). "
        f"Interval: {SESSION_CACHE_INTERVAL}s. ROS6 dihandle polling.py."
    )
    while True:
        try:
            await refresh_session_cache()
        except Exception as e:
            logger.error(f"[session_cache] Error: {e}")
        await asyncio.sleep(SESSION_CACHE_INTERVAL)
