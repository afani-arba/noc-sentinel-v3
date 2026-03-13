#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — Update Script v3.0
# Jalankan di server: sudo bash update.sh
#                     atau: sudo noc-update
# =============================================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

print_step() { echo -e "\n${BOLD}${BLUE}═══ $1 ═══${NC}"; }
print_ok()   { echo -e "  ${GREEN}✓ $1${NC}"; }
print_warn() { echo -e "  ${YELLOW}⚠ $1${NC}"; }
print_err()  { echo -e "\n${RED}${BOLD}✗ ERROR: $1${NC}\n"; exit 1; }

APP_DIR="/opt/noc-sentinel-v3"
SERVICE="nocsentinel"

[[ $EUID -ne 0 ]] && print_err "Jalankan sebagai root: sudo bash update.sh"
[[ ! -d "$APP_DIR/.git" ]] && print_err "Direktori $APP_DIR tidak ditemukan atau bukan git repo"

echo -e "${BOLD}${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         NOC Sentinel v3 — Update Script v3.0                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  Waktu    : $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "  Service  : $SERVICE"
echo -e "  Direktori: $APP_DIR"
echo ""

# ── 0. Cek & perbaiki .env ────────────────────────────────────────────────────
print_step "0/7 Memeriksa konfigurasi .env"
ENV_FILE="$APP_DIR/backend/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    print_warn ".env tidak ditemukan — menyalin dari .env.example"
    cp "$APP_DIR/backend/.env.example" "$ENV_FILE"
    print_warn "PERHATIAN: Edit $ENV_FILE sebelum melanjutkan!"
    read -rp "Tekan ENTER setelah selesai edit .env ..."
fi

JWT_CHECK=$(grep -E "^(JWT_SECRET|SECRET_KEY)=.{8,}" "$ENV_FILE" 2>/dev/null | head -1 || true)
if [[ -z "$JWT_CHECK" ]]; then
    print_warn "JWT_SECRET belum dikonfigurasi — auto-generating..."
    NEW_SECRET=$(openssl rand -hex 32)
    echo "" >> "$ENV_FILE"
    echo "# Auto-generated saat update $(date +%Y-%m-%d)" >> "$ENV_FILE"
    echo "JWT_SECRET=$NEW_SECRET" >> "$ENV_FILE"
    print_ok "JWT_SECRET di-generate dan disimpan ke .env"
else
    print_ok "JWT_SECRET sudah dikonfigurasi"
fi

# ── 1. Git Pull ───────────────────────────────────────────────────────────────
print_step "1/7 Pull update terbaru dari GitHub"
cd "$APP_DIR"

git fetch origin 2>/dev/null || print_warn "Tidak bisa fetch dari GitHub — cek koneksi internet"

LOCAL=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "")

if [[ -n "$LOCAL" && "$LOCAL" == "$REMOTE" ]]; then
    print_warn "Sudah up-to-date (commit: $(git rev-parse --short HEAD))"
else
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || print_err "Git pull gagal"
    print_ok "Update ke: $(git rev-parse --short HEAD) — $(git log -1 --format='%s')"
fi

# ── 2. Update Python dependencies ────────────────────────────────────────────
print_step "2/7 Update Python dependencies"

if [[ ! -d "$APP_DIR/backend/venv" ]]; then
    print_warn "venv tidak ditemukan, membuat venv baru..."
    python3.11 -m venv "$APP_DIR/backend/venv" 2>/dev/null || python3 -m venv "$APP_DIR/backend/venv"
fi

source "$APP_DIR/backend/venv/bin/activate"

# Hapus paket lama yang tidak diperlukan
for pkg in pysnmp pysnmp-lextudio pyasn1-modules pysmi-lextudio; do
    if pip show "$pkg" &>/dev/null 2>&1; then
        pip uninstall -y "$pkg" 2>/dev/null || true
    fi
done

pip install --upgrade pip -q
pip install -r "$APP_DIR/backend/requirements.txt" -q
deactivate
print_ok "Python packages updated"

# ── 3. Build frontend (npm + Vite) ────────────────────────────────────────────
print_step "3/7 Build frontend (npm + Vite)"
cd "$APP_DIR/frontend"

npm install --legacy-peer-deps --prefer-offline 2>/dev/null || npm install --legacy-peer-deps
npm run build

if [[ ! -f "build/index.html" ]]; then
    print_err "Build gagal — build/index.html tidak ditemukan!"
fi
print_ok "Frontend build selesai → build/"

# ── 4. Update systemd service ─────────────────────────────────────────────────
print_step "4/7 Update systemd service"

cat > "/etc/systemd/system/${SERVICE}.service" <<SVCEOF
[Unit]
Description=NOC Sentinel v3 Backend (FastAPI/Uvicorn)
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=${APP_DIR}/backend/venv/bin/uvicorn server:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --loop asyncio \
    --access-log \
    --log-level info
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=5
StartLimitIntervalSec=120
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE}
KillMode=mixed
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable "${SERVICE}" --quiet
systemctl enable mongod --quiet 2>/dev/null || true
systemctl enable nginx  --quiet 2>/dev/null || true

# Copy ke /usr/local/bin untuk akses mudah
cp "$APP_DIR/update.sh" /usr/local/bin/noc-update 2>/dev/null || true
chmod +x /usr/local/bin/noc-update 2>/dev/null || true

print_ok "Systemd service dikonfigurasi"

# ── 5. Restart backend ────────────────────────────────────────────────────────
print_step "5/7 Restart backend service"
systemctl restart "$SERVICE"
sleep 4

if systemctl is-active --quiet "$SERVICE"; then
    print_ok "Backend '$SERVICE': RUNNING ✓"
else
    echo -e "${RED}✗ Backend gagal start! Error log:${NC}"
    journalctl -u "$SERVICE" -n 30 --no-pager
    print_warn "Tips: pastikan JWT_SECRET dan MONGO_URI sudah benar di $ENV_FILE"
    exit 1
fi

systemctl reload nginx 2>/dev/null && print_ok "Nginx di-reload" || true

# ── 6. Verifikasi health ──────────────────────────────────────────────────────
print_step "6/7 Verifikasi health endpoint"
sleep 2
if curl -sf http://localhost:8000/api/health 2>/dev/null | grep -q "ok"; then
    print_ok "API health check: OK ✓"
else
    print_warn "API health check tidak merespon — cek log: journalctl -u $SERVICE -n 50"
fi

# ── 7. Ringkasan ─────────────────────────────────────────────────────────────
print_step "7/7 Selesai!"
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗"
echo    "║                  ✅ UPDATE SELESAI!                           ║"
echo -e "╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Commit  :${NC}  $(git -C $APP_DIR rev-parse --short HEAD) — $(git -C $APP_DIR log -1 --format='%s')"
echo -e "  ${BOLD}Backend :${NC}  $(systemctl is-active $SERVICE)"
echo -e "  ${BOLD}Nginx   :${NC}  $(systemctl is-active nginx 2>/dev/null || echo 'n/a')"
echo -e "  ${BOLD}MongoDB :${NC}  $(systemctl is-active mongod 2>/dev/null || echo 'n/a')"
echo ""
echo -e "  ${YELLOW}➡ Buka browser → Ctrl+Shift+R untuk melihat perubahan${NC}"
echo -e "  ${YELLOW}➡ Atau update via Web UI: http://SERVER/update${NC}"
echo ""
