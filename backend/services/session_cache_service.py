"""
Session Cache Service — PPPoE & Hotspot Active Count Background Fetcher.

Mengambil jumlah session aktif (PPPoE + Hotspot) dari semua device online
secara paralel, menyimpan hasilnya ke field pppoe_active / hotspot_active
di koleksi devices.

Wallboard membaca nilai ini dari DB (tidak live fetch per request)
sehingga tidak ada flicker/hilang-timbul.

Interval default: 3600 detik (1 jam). Dapat diubah via env SESSION_CACHE_INTERVAL.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from core.db import get_db
from mikrotik_api import get_api_client

logger = logging.getLogger(__name__)

# Interval update dalam detik (default 1 jam = 3600)
SESSION_CACHE_INTERVAL = int(os.environ.get("SESSION_CACHE_INTERVAL", "3600"))

# Timeout per device saat fetch session count
SESSION_FETCH_TIMEOUT = 10   # detik


async def _fetch_one(device: dict) -> tuple[str, int, int]:
    """
    Fetch PPPoE + Hotspot active count untuk satu device.
    Returns (device_id, pppoe_count, hotspot_count).
    Semua exception ditangkap — device yang gagal tidak mengganggu yang lain.
    """
    dev_id = device.get("id", "")
    dev_name = device.get("name", dev_id)
    try:
        mt = get_api_client(device)

        async def safe_list(coro) -> list:
            try:
                result = await asyncio.wait_for(coro, timeout=SESSION_FETCH_TIMEOUT)
                return result if isinstance(result, list) else []
            except Exception:
                return []

        pppoe_list, hotspot_list = await asyncio.gather(
            safe_list(mt.list_pppoe_active()),
            safe_list(mt.list_hotspot_active()),
        )
        pppoe_count   = len(pppoe_list)
        hotspot_count = len(hotspot_list)
        logger.debug(
            f"[session_cache] {dev_name}: pppoe={pppoe_count} hotspot={hotspot_count}"
        )
        return dev_id, pppoe_count, hotspot_count

    except Exception as e:
        logger.warning(f"[session_cache] Gagal fetch {dev_name}: {e}")
        return dev_id, -1, -1   # -1 = keep existing value


async def refresh_session_cache():
    """
    Fetch session counts dari SEMUA device online secara paralel,
    lalu update field pppoe_active / hotspot_active di DB.
    Data lama otomatis tertimpa (upsert via $set) — tidak perlu delete manual.
    """
    db = get_db()
    # Ambil semua device online dengan full credentials
    devices = await db.devices.find(
        {"status": "online"},
        {"_id": 0}   # include api_password untuk auth
    ).to_list(500)

    if not devices:
        logger.info("[session_cache] Tidak ada device online, skip.")
        return

    logger.info(f"[session_cache] Memulai refresh untuk {len(devices)} device online...")

    # Fetch semua device secara paralel
    results = await asyncio.gather(
        *[_fetch_one(d) for d in devices],
        return_exceptions=True,
    )

    # Update DB
    updated = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()

    for result in results:
        if isinstance(result, Exception):
            skipped += 1
            continue
        dev_id, pppoe, hotspot = result
        if not dev_id:
            skipped += 1
            continue
        if pppoe == -1 and hotspot == -1:
            # Fetch gagal — pertahankan nilai lama
            skipped += 1
            continue

        await db.devices.update_one(
            {"id": dev_id},
            {"$set": {
                "pppoe_active":        pppoe,
                "hotspot_active":      hotspot,
                "session_cache_at":    now,   # timestamp update terakhir
            }},
        )
        updated += 1

    logger.info(
        f"[session_cache] Selesai: {updated} device diupdate, "
        f"{skipped} device di-skip (offline/gagal). "
        f"Interval berikutnya: {SESSION_CACHE_INTERVAL}s "
        f"({SESSION_CACHE_INTERVAL // 60} menit)."
    )


async def session_cache_loop():
    """
    Background loop: jalankan refresh_session_cache() setiap SESSION_CACHE_INTERVAL detik.
    Fetch pertama dijalankan 30 detik setelah server start (beri waktu polling stabilize).
    """
    logger.info(
        f"[session_cache] Service dimulai. "
        f"Interval: {SESSION_CACHE_INTERVAL}s ({SESSION_CACHE_INTERVAL // 60} menit). "
        f"Fetch pertama dalam 30 detik..."
    )
    await asyncio.sleep(30)   # tunggu polling pertama selesai

    while True:
        try:
            await refresh_session_cache()
        except Exception as e:
            logger.error(f"[session_cache] Error tidak terduga: {e}")

        await asyncio.sleep(SESSION_CACHE_INTERVAL)
