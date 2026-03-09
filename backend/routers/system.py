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

# Directory of server.py parent (project root)
APP_DIR = str(Path(__file__).parent.parent.parent)


@router.get("/check-update")
async def check_update(user=Depends(require_admin)):
    """Check if there are updates available from GitHub."""
    try:
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
        )
        current_commit = current.stdout.strip() if current.returncode == 0 else None

        fetch = subprocess.run(
            ["git", "fetch", "origin"], capture_output=True, text=True, cwd=APP_DIR, timeout=30
        )
        if fetch.returncode != 0:
            return {
                "has_update": False, "current_commit": current_commit,
                "message": "Tidak dapat terhubung ke repository.", "error": fetch.stderr
            }

        remote = subprocess.run(
            ["git", "rev-parse", "origin/main"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
        )
        if remote.returncode != 0:
            remote = subprocess.run(
                ["git", "rev-parse", "origin/master"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
        if remote.returncode != 0:
            return {"has_update": False, "current_commit": current_commit, "message": "Branch remote tidak ditemukan."}

        latest_commit = remote.stdout.strip()
        has_update = current_commit != latest_commit
        commits_behind = 0
        if has_update:
            count = subprocess.run(
                ["git", "rev-list", "--count", "HEAD..origin/main"],
                capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
            if count.returncode == 0:
                commits_behind = int(count.stdout.strip())

        return {
            "has_update": has_update, "current_commit": current_commit,
            "latest_commit": latest_commit, "commits_behind": commits_behind,
            "message": "Update tersedia!" if has_update else "Aplikasi sudah versi terbaru."
        }
    except subprocess.TimeoutExpired:
        return {"has_update": False, "message": "Timeout saat mengecek update.", "error": "timeout"}
    except Exception as e:
        logger.error(f"Check update error: {e}")
        return {"has_update": False, "message": f"Error: {str(e)}", "error": str(e)}


@router.post("/perform-update")
async def perform_update(user=Depends(require_admin)):
    """Pull latest changes from GitHub — runs in background thread to avoid blocking event loop."""
    log = []
    backend_dir = str(Path(__file__).parent.parent)
    frontend_dir = str(Path(__file__).parent.parent.parent / "frontend")

    def _do_update():
        nonlocal log
        log.append("Menjalankan git pull...")
        pull = subprocess.run(
            ["git", "pull", "origin", "main"], capture_output=True, text=True, cwd=APP_DIR, timeout=60
        )
        if pull.returncode != 0:
            pull = subprocess.run(
                ["git", "pull", "origin", "master"], capture_output=True, text=True, cwd=APP_DIR, timeout=60
            )
        if pull.returncode != 0:
            log.append(f"Error git pull: {pull.stderr}")
            return {"success": False, "log": log, "error": pull.stderr}

        log.append(pull.stdout if pull.stdout else "Git pull berhasil")

        log.append("Menginstall dependensi backend...")
        pip = subprocess.run(
            ["pip", "install", "-r", "requirements.txt"],
            capture_output=True, text=True, cwd=backend_dir, timeout=120
        )
        log.append("Backend deps ok" if pip.returncode == 0 else f"Warning pip: {pip.stderr[:200]}")

        log.append("Menginstall dependensi frontend...")
        yarn = subprocess.run(
            ["yarn", "install"], capture_output=True, text=True, cwd=frontend_dir, timeout=120
        )
        log.append("Frontend deps ok" if yarn.returncode == 0 else f"Warning yarn: {yarn.stderr[:200]}")

        log.append("Building frontend...")
        build = subprocess.run(
            ["yarn", "build"], capture_output=True, text=True, cwd=frontend_dir, timeout=300
        )
        log.append("Frontend build ok" if build.returncode == 0 else f"Warning build: {build.stderr[:200]}")

        # Restart service
        log.append("Mencoba restart services...")
        try:
            subprocess.run(["sudo", "supervisorctl", "restart", "backend"], timeout=10)
            subprocess.run(["sudo", "supervisorctl", "restart", "frontend"], timeout=10)
            log.append("Services di-restart via supervisor")
        except Exception:
            for svc in ["noc-backend", "noc-sentinel", "noc-sentinel-backend"]:
                try:
                    r = subprocess.run(["sudo", "systemctl", "restart", svc], capture_output=True, timeout=10)
                    if r.returncode == 0:
                        log.append(f"{svc} di-restart via systemd")
                        break
                except Exception:
                    continue
            else:
                log.append("Note: Silakan restart service secara manual")

        log.append("Update selesai!")
        return {"success": True, "log": log}

    try:
        result = await asyncio.to_thread(_do_update)
        return result
    except Exception as e:
        logger.error(f"Update error: {e}")
        log.append(f"Error: {str(e)}")
        return {"success": False, "log": log, "error": str(e)}


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
