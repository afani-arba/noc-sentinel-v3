"""
NOC-Sentinel Backend - Modular Entry Point (v3.0)
v3: Added Wall Display, SLA Monitoring, Incident Management, Audit Log,
    Top Talkers, Heatmap features.

Structure:
  core/       - db singleton, auth helpers, polling loop
  routers/    - one file per feature domain
  services/   - business logic (notifications, backups)
  syslog_server.py - UDP syslog receiver
"""
import os
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

# ── Bootstrap ──────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ── DB must init before routers import ────────────────────────────────────
from core.db import init_db
init_db()

# ── Import routers ─────────────────────────────────────────────────────────
from fastapi import APIRouter
from routers.auth import router as auth_router
from routers.devices import router as devices_router
from routers.pppoe import router as pppoe_router
from routers.hotspot import router as hotspot_router
from routers.reports import router as reports_router
from routers.admin import router as admin_router
from routers.system import router as system_router
from routers.notifications import router as notifications_router
from routers.backups import router as backups_router
from routers.syslog import router as syslog_router
from routers.metrics import router as metrics_router
from routers.routing import router as routing_router
from routers.genieacs import router as genieacs_router
from routers.customers import router as customers_router
from routers.billing import router as billing_router
from routers.wallboard import router as wallboard_router
from routers.sla import router as sla_router
from routers.incidents import router as incidents_router
from routers.audit import router as audit_router
from routers.events import router as events_router
from routers.scheduler import router as scheduler_router
from routers.speedtest import router as speedtest_router
from routers.routing_alerts import router as routing_alerts_router
from routers.wireguard import router as wireguard_router
from routers.peering_eye import router as peering_eye_router
from routers.license import router as license_router

# ── Background task references (FIX BUG #3: simpan reference agar tidak di-GC) ──
_background_tasks: list = []


# ── Lifespan (FIX BUG #2: ganti deprecated @app.on_event) ────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: startup → yield → shutdown"""
    logger.info("NOC-Sentinel v3.0 starting up...")

    # Start device polling background task
    from core.polling import polling_loop
    poll_task = asyncio.create_task(polling_loop())
    _background_tasks.append(poll_task)  # FIX BUG #3: simpan reference
    logger.info("Polling loop started")

    # Start SSE device event poller
    from routers.events import start_poller
    sse_task = start_poller()
    _background_tasks.append(sse_task)   # FIX BUG #3: simpan reference
    logger.info("SSE event poller started")

    # Start UDP syslog server
    # FIX BUG #1: gunakan get_running_loop() bukan get_event_loop()
    loop = asyncio.get_running_loop()
    from syslog_server import start_syslog_server
    syslog_tasks = await start_syslog_server(loop)
    if syslog_tasks:
        _background_tasks.extend(syslog_tasks)  # FIX BUG #3: simpan reference

    # Start auto-backup scheduler
    from services.backup_service import auto_backup_loop
    backup_task = asyncio.create_task(auto_backup_loop())
    _background_tasks.append(backup_task)
    logger.info("Auto backup scheduler started")

    # Start auto-isolir scheduler
    from services.isolir_service import auto_isolir_loop
    isolir_task = asyncio.create_task(auto_isolir_loop())
    _background_tasks.append(isolir_task)
    logger.info("Auto isolir scheduler started")

    # Start BGP/OSPF alert monitor
    from services.routing_alert_service import bgp_ospf_alert_loop
    bgp_task = asyncio.create_task(bgp_ospf_alert_loop())
    _background_tasks.append(bgp_task)
    logger.info("BGP/OSPF alert monitor started")

    # Start speed test scheduler
    from services.speedtest_service import speedtest_loop
    speedtest_task = asyncio.create_task(speedtest_loop())
    _background_tasks.append(speedtest_task)
    logger.info("Speed test scheduler started")

    # Start PPPoE & Hotspot session cache updater
    from services.session_cache_service import session_cache_loop
    session_task = asyncio.create_task(session_cache_loop())
    _background_tasks.append(session_task)
    logger.info("Session cache service started (PPPoE & Hotspot count, interval=1h)")

    # Start WireGuard tunnel if enabled
    try:
        from core.db import get_db
        db = get_db()
        wg_cfg = await db.settings.find_one({"_id": "wireguard_config"})
        if wg_cfg and wg_cfg.get("enabled"):
            import core.wireguard_service as wg_svc
            logger.info("WireGuard Client enabled in DB, trying to wg-quick up wg0...")
            ok, out = wg_svc.wg_up()
            if ok:
                logger.info("WireGuard wg0 started successfully on boot.")
            else:
                logger.warning(f"Failed to start WireGuard on boot: {out}")
    except Exception as e:
        logger.error(f"Error checking WireGuard startup config: {e}")

    # Start License Verification
    from services.license_service import license_check_loop
    license_task = asyncio.create_task(license_check_loop())
    _background_tasks.append(license_task)
    logger.info("License Verification loop started")

    logger.info("NOC-Sentinel ready!")
    
    yield  # Server berjalan di sini


    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("NOC-Sentinel shutting down...")
    # Cancel semua background tasks
    for task in _background_tasks:
        if not task.done():
            task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    from core.db import close_db
    close_db()
    logger.info("NOC-Sentinel shutdown complete")


# ── App factory ────────────────────────────────────────────────────────────
app = FastAPI(title="NOC-Sentinel API", version="3.0.0", lifespan=lifespan)

# FIX BUG #4: CORS — jika origins = "*", nonaktifkan credentials agar compatible
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "").strip()
if _cors_origins_raw and _cors_origins_raw != "*":
    _cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
    _allow_credentials = True
else:
    # Wildcard — credentials harus False (spec CORS tidak izinkan keduanya)
    _cors_origins = ["*"]
    _allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_credentials=_allow_credentials,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# FIX BUG #5: License verification middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from core.db import get_db

@app.middleware("http")
async def license_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        allowed = ["/api/auth/login", "/api/system/license", "/api/syslog/"] # Allow auth and license update
        if not any(path.startswith(p) for p in allowed):
            try:
                # Middleware sync-like, tapi db_settings kita pakai motor async
                # Kita bisa menggunakan request.app.state.db jika diset, atau get_db secara langsung.
                # Opsi aman: buat koneksi temporary atau gunakan koneksi single db
                db = await anext(get_db())
                status_doc = await db.system_settings.find_one({"_id": "license_status"})
                status = status_doc.get("status") if status_doc else "unlicensed"
                if status != "valid":
                    return JSONResponse(status_code=403, content={"detail": f"License Error: {status_doc.get('message', 'Unlicensed')}"})
            except Exception as e:
                # Fallback if DB not ready
                pass

    return await call_next(request)

# Mount all routers under /api prefix
api = APIRouter(prefix="/api")
api.include_router(auth_router)
api.include_router(devices_router)
api.include_router(pppoe_router)
api.include_router(hotspot_router)
api.include_router(reports_router)
api.include_router(admin_router)
api.include_router(system_router)
api.include_router(notifications_router)
api.include_router(backups_router)
api.include_router(syslog_router)
api.include_router(metrics_router)
api.include_router(routing_router)
api.include_router(genieacs_router)
api.include_router(customers_router)
api.include_router(billing_router)
api.include_router(wallboard_router)
api.include_router(sla_router)
api.include_router(incidents_router)
api.include_router(audit_router)
api.include_router(events_router)
api.include_router(scheduler_router)
api.include_router(speedtest_router)
api.include_router(routing_alerts_router)
api.include_router(wireguard_router)
api.include_router(peering_eye_router)
api.include_router(license_router)
app.include_router(api)


@app.get("/")
async def root():
    return {"status": "ok", "service": "NOC-Sentinel", "version": "3.0.0"}
