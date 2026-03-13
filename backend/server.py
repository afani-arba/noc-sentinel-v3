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
from routers.firewall import router as firewall_router
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
api.include_router(firewall_router)
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
app.include_router(api)


@app.get("/")
async def root():
    return {"status": "ok", "service": "NOC-Sentinel", "version": "3.0.0"}
