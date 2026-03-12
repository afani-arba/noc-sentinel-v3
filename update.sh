#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — Update Script
# Jalankan di server: sudo bash update.sh
# =============================================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

print_step() { echo -e "\n${BOLD}${GREEN}▶ $1${NC}"; }
print_ok()   { echo -e "${GREEN}✓ $1${NC}"; }
print_warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_err()  { echo -e "${RED}✗ $1${NC}"; exit 1; }

APP_DIR="/opt/noc-sentinel-v3"
SERVICE="nocsentinel"

[[ $EUID -ne 0 ]] && print_err "Jalankan sebagai root: sudo bash update.sh"
[[ ! -d "$APP_DIR/.git" ]] && print_err "Direktori $APP_DIR tidak ditemukan atau bukan git repo"

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║      NOC Sentinel v3 — Update Script                 ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. Pull dari GitHub ───────────────────────────────────────────────────────
print_step "1/6 Pull update terbaru dari GitHub"
cd "$APP_DIR"
git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [[ "$LOCAL" == "$REMOTE" ]]; then
    print_warn "Sudah up-to-date, tidak ada perubahan baru"
else
    git pull origin main
    print_ok "Code diperbarui ke commit $(git rev-parse --short HEAD)"
fi

# ── 2. Update Python dependencies ────────────────────────────────────────────
print_step "2/6 Update Python dependencies"
source "$APP_DIR/backend/venv/bin/activate"

# Hapus paket SNMP lama jika masih terinstall (one-time cleanup)
if pip show pysnmp-lextudio &>/dev/null 2>&1; then
    print_warn "Menghapus paket SNMP lama..."
    pip uninstall -y pysnmp-lextudio pyasn1 pyasn1-modules pysmi-lextudio 2>/dev/null || true
    print_ok "Paket SNMP lama dihapus"
fi

pip install -r "$APP_DIR/backend/requirements.txt" -q
deactivate
print_ok "Python packages updated"

# ── 3. Build frontend ─────────────────────────────────────────────────────────
print_step "3/6 Build frontend (npm)"
cd "$APP_DIR/frontend"
npm install --silent
npm run build
[[ -f "build/index.html" ]] || print_err "Build gagal!"
print_ok "Frontend berhasil di-build"

# ── 4. Setup/verifikasi systemd service ──────────────────────────────────────
print_step "4/6 Setup systemd service (auto-start)"

cat > "/etc/systemd/system/${SERVICE}.service" <<SVCEOF
[Unit]
Description=NOC Sentinel v3 Backend (FastAPI)
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=${APP_DIR}/backend/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1 --loop asyncio
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE}

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable "${SERVICE}" --quiet
print_ok "Service '${SERVICE}' aktif dan akan auto-start saat reboot"

# Pastikan MongoDB + Nginx juga auto-start
systemctl enable mongod --quiet 2>/dev/null || true
systemctl enable nginx  --quiet 2>/dev/null || true
print_ok "MongoDB + Nginx dikonfigurasi untuk auto-start"

# ── 5. Restart service ────────────────────────────────────────────────────────
print_step "5/6 Restart layanan"
systemctl restart "$SERVICE"
sleep 3

if systemctl is-active --quiet "$SERVICE"; then
    print_ok "Backend '${SERVICE}': RUNNING ✓"
else
    echo -e "${RED}✗ Backend gagal start! Cek log:${NC}"
    journalctl -u "$SERVICE" -n 30 --no-pager
    exit 1
fi

# Reload nginx agar static build terbaru terbaca
systemctl reload nginx 2>/dev/null && print_ok "Nginx di-reload" || true

# ── 6. Verifikasi kesehatan API ───────────────────────────────────────────────
print_step "6/6 Verifikasi health endpoint"
sleep 2
if curl -sf http://localhost:8000/api/health | grep -q "ok"; then
    print_ok "API health check: OK"
else
    print_warn "API health check tidak merespon — cek log: journalctl -u $SERVICE -n 50"
fi

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗"
echo    "║          ✅ UPDATE SELESAI!                           ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Commit aktif  :${NC}  $(git -C $APP_DIR rev-parse --short HEAD) — $(git -C $APP_DIR log -1 --format='%s')"
echo -e "  ${BOLD}Backend status :${NC} $(systemctl is-active $SERVICE)"
echo ""
echo -e "  Buka browser → ${BOLD}Ctrl+Shift+R${NC} (hard refresh) untuk melihat perubahan"
echo ""
