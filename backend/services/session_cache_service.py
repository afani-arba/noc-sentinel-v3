"""
Session Cache Service — PPPoE & Hotspot Active Count Background Fetcher.

Mengambil jumlah session aktif (PPPoE + Hotspot) dari semua device online
secara paralel (dibatasi 10 concurrent), menyimpan ke field pppoe_active /
hotspot_active di koleksi devices.

Wallboard membaca nilai ini dari DB (tidak live fetch per request)
→ tidak ada flicker/hilang-timbul.

Interval default: 300 detik (5 menit). Ubah via env SESSION_CACHE_INTERVAL.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from core.db import get_db
from mikrotik_api import get_api_client

logger = logging.getLogger(__name__)

# Interval update dalam detik (default 5 menit = 300)
SESSION_CACHE_INTERVAL = int(os.environ.get("SESSION_CACHE_INTERVAL", "300"))

# Timeout per device — ROS6 API Protocol lebih lambat dari REST API
SESSION_FETCH_TIMEOUT = 25   # detik

# Concurrency limit — cegah overload server dengan terlalu banyak koneksi paralel
SESSION_MAX_CONCURRENT = 10


async def _fetch_one(device: dict) -> tuple[str, int, int]:
    """
    Fetch PPPoE + Hotspot active count untuk satu device.
    Returns (device_id, pppoe_count, hotspot_count).
    -1 berarti gagal → pertahankan nilai lama di DB.
    """
    dev_id   = device.get("id", "")
    dev_name = device.get("name", dev_id)
    api_mode = device.get("api_mode", "rest")

    try:
        mt = get_api_client(device)

        pppoe_count   = 0
        hotspot_count = 0

        # Fetch PPPoE active — error individual tidak batalkan hotspot fetch
        try:
            pppoe_list = await asyncio.wait_for(
                mt.list_pppoe_active(), timeout=SESSION_FETCH_TIMEOUT
            )
            pppoe_count = len(pppoe_list) if isinstance(pppoe_list, list) else 0
        except asyncio.TimeoutError:
            logger.warning(f"[session_cache] Timeout PPPoE {dev_name} (mode={api_mode})")
            pppoe_count = -1
        except NotImplementedError:
            pass
        except Exception as e:
            logger.debug(f"[session_cache] PPPoE gagal {dev_name}: {type(e).__name__}: {e}")

        # Fetch Hotspot active
        try:
            hs_list = await asyncio.wait_for(
                mt.list_hotspot_active(), timeout=SESSION_FETCH_TIMEOUT
            )
            hotspot_count = len(hs_list) if isinstance(hs_list, list) else 0
        except asyncio.TimeoutError:
            logger.warning(f"[session_cache] Timeout Hotspot {dev_name} (mode={api_mode})")
            hotspot_count = -1
        except NotImplementedError:
            pass
        except Exception as e:
            logger.debug(f"[session_cache] Hotspot gagal {dev_name}: {type(e).__name__}: {e}")

        logger.info(
            f"[session_cache] {dev_name} ({api_mode}): "
            f"pppoe={pppoe_count} hotspot={hotspot_count}"
        )
        return dev_id, pppoe_count, hotspot_count

    except Exception as e:
        logger.warning(f"[session_cache] Gagal koneksi {dev_name}: {type(e).__name__}: {e}")
        return dev_id, -1, -1


async def refresh_session_cache():
    """
    Fetch session counts dari SEMUA device online secara paralel terbatas,
    lalu update field pppoe_active / hotspot_active di DB.
    """
    db = get_db()
    devices = await db.devices.find(
        {"status": "online"},
        {"_id": 0}   # include api_password untuk auth
    ).to_list(500)

    if not devices:
        logger.info("[session_cache] Tidak ada device online.")
        return

    logger.info(
        f"[session_cache] Refresh {len(devices)} device "
        f"(concurrent={SESSION_MAX_CONCURRENT}, timeout={SESSION_FETCH_TIMEOUT}s)..."
    )

    # Semaphore batasi concurrent connections
    sem = asyncio.Semaphore(SESSION_MAX_CONCURRENT)

    async def throttled(device):
        async with sem:
            return await _fetch_one(device)

    results = await asyncio.gather(
        *[throttled(d) for d in devices],
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

        # Build $set — hanya update field yang berhasil di-fetch (bukan -1)
        set_fields: dict = {"session_cache_at": now}
        if pppoe >= 0:
            set_fields["pppoe_active"] = pppoe
        if hotspot >= 0:
            set_fields["hotspot_active"] = hotspot

        if len(set_fields) <= 1:
            # Hanya timestamp — keduanya gagal
            skipped += 1
            continue

        await db.devices.update_one({"id": dev_id}, {"$set": set_fields})
        updated += 1

    logger.info(
        f"[session_cache] Selesai: {updated} diupdate, {skipped} skip. "
        f"Interval berikutnya {SESSION_CACHE_INTERVAL}s."
    )


async def session_cache_loop():
    """
    Background loop: refresh_session_cache() setiap SESSION_CACHE_INTERVAL detik.
    Fetch PERTAMA dijalankan LANGSUNG saat server start (tidak ada delay).
    """
    logger.info(
        f"[session_cache] Service dimulai. "
        f"Interval: {SESSION_CACHE_INTERVAL}s ({SESSION_CACHE_INTERVAL // 60} menit). "
        f"Fetch pertama dimulai sekarang..."
    )

    while True:
        try:
            await refresh_session_cache()
        except Exception as e:
            logger.error(f"[session_cache] Error: {e}")

        await asyncio.sleep(SESSION_CACHE_INTERVAL)
