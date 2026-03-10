"""
System update router: check and perform application updates.
"""
import os
import asyncio
import subprocess
import logging
from pathlib import Path
from fastapi import APIRouter, Depends
from core.auth import require_admin

router = APIRouter(prefix="/system", tags=["system"])
logger = logging.getLogger(__name__)

# Project root: /opt/noc-sentinel  (parent of backend/)
APP_DIR = str(Path(__file__).parent.parent.parent)
BACKEND_DIR = str(Path(__file__).parent.parent)
FRONTEND_DIR = str(Path(__file__).parent.parent.parent / "frontend")

# Candidate paths
VENV_PIP  = str(Path(BACKEND_DIR) / "venv" / "bin" / "pip")
UPDATE_SH = str(Path(APP_DIR) / "update.sh")
SERVICE_NAME = "noc-backend"


@router.get("/check-update")
async def check_update(user=Depends(require_admin)):
    """Check if there are updates available from GitHub."""
    try:
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
        )
        current_commit = current.stdout.strip() if current.returncode == 0 else None

        # Get current commit message
        current_msg = ""
        if current_commit:
            msg_result = subprocess.run(
                ["git", "log", "-1", "--pretty=%s"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
            current_msg = msg_result.stdout.strip() if msg_result.returncode == 0 else ""

        fetch = subprocess.run(
            ["git", "fetch", "origin"], capture_output=True, text=True, cwd=APP_DIR, timeout=30
        )
        if fetch.returncode != 0:
            return {
                "has_update": False, "current_commit": current_commit,
                "current_message": current_msg,
                "message": "Tidak dapat terhubung ke repository.", "error": fetch.stderr
            }

        # Try main, then master
        remote = subprocess.run(
            ["git", "rev-parse", "origin/main"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
        )
        if remote.returncode != 0:
            remote = subprocess.run(
                ["git", "rev-parse", "origin/master"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
        if remote.returncode != 0:
            return {"has_update": False, "current_commit": current_commit, "current_message": current_msg, "message": "Branch remote tidak ditemukan."}

        latest_commit = remote.stdout.strip()
        has_update = current_commit != latest_commit

        commits_behind = 0
        latest_message = ""
        latest_date = ""

        if has_update:
            count = subprocess.run(
                ["git", "rev-list", "--count", "HEAD..origin/main"],
                capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
            if count.returncode == 0:
                try:
                    commits_behind = int(count.stdout.strip())
                except ValueError:
                    commits_behind = 0

            # Get latest commit message on remote
            msg_r = subprocess.run(
                ["git", "log", "origin/main", "-1", "--pretty=%s"],
                capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
            latest_message = msg_r.stdout.strip() if msg_r.returncode == 0 else ""

            date_r = subprocess.run(
                ["git", "log", "origin/main", "-1", "--pretty=%ci"],
                capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
            latest_date = date_r.stdout.strip()[:19] if date_r.returncode == 0 else ""

        return {
            "has_update": has_update,
            "current_commit": current_commit,
            "current_message": current_msg,
            "latest_commit": latest_commit,
            "latest_message": latest_message,
            "latest_date": latest_date,
            "commits_behind": commits_behind,
            "message": "Update tersedia!" if has_update else "Aplikasi sudah versi terbaru."
        }
    except subprocess.TimeoutExpired:
        return {"has_update": False, "message": "Timeout saat mengecek update.", "error": "timeout"}
    except Exception as e:
        logger.error(f"Check update error: {e}")
        return {"has_update": False, "message": f"Error: {str(e)}", "error": str(e)}


@router.post("/perform-update")
async def perform_update(user=Depends(require_admin)):
    """Pull latest changes from GitHub and rebuild frontend."""
    log = []

    def _do_update():
        nonlocal log

        # ── Try update.sh first (most reliable) ──────────────────────────
        if Path(UPDATE_SH).exists():
            log.append(f"Menjalankan update.sh...")
            result = subprocess.run(
                ["bash", UPDATE_SH],
                capture_output=True, text=True, cwd=APP_DIR, timeout=600
            )
            output_lines = (result.stdout + result.stderr).splitlines()
            for line in output_lines:
                if line.strip():
                    log.append(line.strip())
            if result.returncode == 0:
                log.append("Update selesai!")
                return {"success": True, "log": log}
            else:
                log.append(f"update.sh gagal (exit {result.returncode}), mencoba metode manual...")
                log = ["Fallback ke metode manual..."]

        # ── Fallback: inline steps ────────────────────────────────────────
        log.append("Menjalankan git pull...")
        pull = subprocess.run(
            ["git", "pull", "origin", "main"], capture_output=True, text=True, cwd=APP_DIR, timeout=60
        )
        if pull.returncode != 0:
            # try master
            pull = subprocess.run(
                ["git", "pull", "origin", "master"], capture_output=True, text=True, cwd=APP_DIR, timeout=60
            )
        if pull.returncode != 0:
            log.append(f"Error git pull: {pull.stderr.strip()}")
            return {"success": False, "log": log, "error": pull.stderr}
        log.append(pull.stdout.strip() or "Git pull berhasil")

        # Install backend deps dengan venv pip
        log.append("Menginstall dependensi backend...")
        pip_cmd = VENV_PIP if Path(VENV_PIP).exists() else "pip3"
        pip = subprocess.run(
            [pip_cmd, "install", "-r", "requirements.txt", "-q"],
            capture_output=True, text=True, cwd=BACKEND_DIR, timeout=180
        )
        log.append("Backend deps ok" if pip.returncode == 0 else f"Warning pip: {pip.stderr[:300]}")

        # Install frontend deps
        log.append("Menginstall dependensi frontend...")
        yarn_path = subprocess.run(["which", "yarn"], capture_output=True, text=True).stdout.strip() or "yarn"
        yarn_install = subprocess.run(
            [yarn_path, "install", "--silent"],
            capture_output=True, text=True, cwd=FRONTEND_DIR, timeout=180
        )
        log.append("Frontend deps ok" if yarn_install.returncode == 0 else f"Warning yarn install: {yarn_install.stderr[:300]}")

        # Build frontend
        log.append("Building frontend...")
        yarn_build = subprocess.run(
            [yarn_path, "build"],
            capture_output=True, text=True, cwd=FRONTEND_DIR, timeout=600,
            env={**dict(os.environ), "CI": "false", "DISABLE_ESLINT_PLUGIN": "true"}
        )
        if yarn_build.returncode == 0:
            log.append("Frontend build berhasil!")
        else:
            log.append(f"Warning build: {yarn_build.stderr[:400]}")

        # Restart service
        log.append(f"Merestart service {SERVICE_NAME}...")
        try:
            restart = subprocess.run(
                ["sudo", "systemctl", "restart", SERVICE_NAME],
                capture_output=True, text=True, timeout=30
            )
            if restart.returncode == 0:
                log.append(f"Service {SERVICE_NAME} berhasil di-restart!")
            else:
                log.append(f"Note: Restart manual diperlukan — sudo systemctl restart {SERVICE_NAME}")
        except Exception as e:
            log.append(f"Note: Silakan restart service manual: sudo systemctl restart {SERVICE_NAME}")

        log.append("Update selesai!")
        return {"success": True, "log": log}

    try:
        result = await asyncio.to_thread(_do_update)
        return result
    except Exception as e:
        logger.error(f"Update error: {e}")
        log.append(f"Error: {str(e)}")
        return {"success": False, "log": log, "error": str(e)}


@router.get("/app-info")
async def app_info():
    """Return current app version info (commit hash, message, date)."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=APP_DIR, timeout=5
        )
        msg = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"], capture_output=True, text=True, cwd=APP_DIR, timeout=5
        )
        date = subprocess.run(
            ["git", "log", "-1", "--pretty=%ci"], capture_output=True, text=True, cwd=APP_DIR, timeout=5
        )
        return {
            "commit": commit.stdout.strip() if commit.returncode == 0 else "unknown",
            "message": msg.stdout.strip() if msg.returncode == 0 else "",
            "date": date.stdout.strip()[:19] if date.returncode == 0 else "",
            "version": "v2.5",
        }
    except Exception:
        return {"commit": "unknown", "message": "", "date": "", "version": "v2.5"}


@router.post("/save-influxdb-config")
async def save_influxdb_config(data: dict, user=Depends(require_admin)):
    """
    Save InfluxDB configuration to the backend .env file.
    Updates INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET.
    """
    backend_dir = Path(__file__).parent.parent
    env_path = backend_dir / ".env"

    url = (data.get("url") or "").strip()
    token = (data.get("token") or "").strip()
    org = (data.get("org") or "").strip()
    bucket = (data.get("bucket") or "noc-sentinel").strip()

    if not url or not token or not org:
        from fastapi import HTTPException
        raise HTTPException(400, "URL, token, dan org wajib diisi")

    # Read existing .env
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    # Keys to update
    new_values = {
        "INFLUXDB_URL": url,
        "INFLUXDB_TOKEN": token,
        "INFLUXDB_ORG": org,
        "INFLUXDB_BUCKET": bucket,
    }

    updated = set()
    new_lines = []
    for line in lines:
        key = line.split("=")[0].strip() if "=" in line else ""
        if key in new_values:
            new_lines.append(f'{key}={new_values[key]}')
            updated.add(key)
        else:
            new_lines.append(line)

    # Append any missing keys
    for key, val in new_values.items():
        if key not in updated:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Also set in current process env so test-connection works immediately
    import os as _os
    _os.environ["INFLUXDB_URL"] = url
    _os.environ["INFLUXDB_TOKEN"] = token
    _os.environ["INFLUXDB_ORG"] = org
    _os.environ["INFLUXDB_BUCKET"] = bucket

    # Reset cached client so next test uses new config
    try:
        import services.metrics_service as _ms
        _ms._influx_enabled = None
        _ms._write_client = None
        _ms._query_client = None
        _ms._write_api = None
        _ms._error_logged = False
    except Exception:
        pass

    logger.info(f"InfluxDB config saved: {url}, org={org}, bucket={bucket}")
    return {"message": "Konfigurasi InfluxDB disimpan. Restart backend tidak diperlukan — sudah aktif."}


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/save-genieacs-config")
async def save_genieacs_config(data: dict, user=Depends(require_admin)):
    """
    Save GenieACS NBI configuration to the backend .env file.
    Updates GENIEACS_URL, GENIEACS_USERNAME, GENIEACS_PASSWORD.
    """
    backend_dir = Path(__file__).parent.parent
    env_path = backend_dir / ".env"

    url = (data.get("url") or "").strip()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not url:
        from fastapi import HTTPException
        raise HTTPException(400, "GENIEACS_URL wajib diisi")

    # Read existing .env
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    new_values = {
        "GENIEACS_URL": url,
        "GENIEACS_USERNAME": username,
        "GENIEACS_PASSWORD": password,
    }

    updated = set()
    new_lines = []
    for line in lines:
        key = line.split("=")[0].strip() if "=" in line else ""
        if key in new_values:
            new_lines.append(f"{key}={new_values[key]}")
            updated.add(key)
        else:
            new_lines.append(line)

    for key, val in new_values.items():
        if key not in updated:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Apply to current process immediately (no restart needed)
    import os as _os
    _os.environ["GENIEACS_URL"] = url
    _os.environ["GENIEACS_USERNAME"] = username
    _os.environ["GENIEACS_PASSWORD"] = password

    # Refresh genieacs_service module globals
    try:
        import services.genieacs_service as _gs
        _gs.GENIEACS_URL = url
        _gs.GENIEACS_USER = username
        _gs.GENIEACS_PASS = password
    except Exception:
        pass

    logger.info(f"GenieACS config saved: {url}, user={username}")
    return {"message": "Konfigurasi GenieACS disimpan dan langsung aktif. Tidak perlu restart."}


@router.get("/genieacs-config")
async def get_genieacs_config(user=Depends(require_admin)):
    """Return current GenieACS config (URL only, password masked)."""
    import os as _os
    return {
        "url": _os.environ.get("GENIEACS_URL", ""),
        "username": _os.environ.get("GENIEACS_USERNAME", ""),
        "password_set": bool(_os.environ.get("GENIEACS_PASSWORD", "")),
    }

