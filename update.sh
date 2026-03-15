#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — Update Script v4.0
# Jalankan: sudo bash update.sh
#           atau: sudo noc-update  (jika sudah diinstall)
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓ $1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠ $1${NC}"; }
err()  { echo -e "\n${RED}${BOLD}✗ ERROR: $1${NC}\n"; exit 1; }
step() { echo -e "\n${BOLD}${BLUE}═══ $1 ═══${NC}"; }

APP_DIR="/opt/noc-sentinel-v3"
ENV_FILE="$APP_DIR/backend/.env"

[[ $EUID -ne 0 ]] && err "Jalankan sebagai root: sudo bash update.sh"
[[ ! -d "$APP_DIR/.git" ]] && err "Direktori $APP_DIR bukan git repo"

# Baca service name dari .env (fallback ke nocsentinel)
SERVICE=$(grep -E "^NOC_SERVICE_NAME=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]') || true
SERVICE="${SERVICE:-nocsentinel}"

echo -e "${BOLD}${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     NOC Sentinel v3 — Update Script v4.0                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  Waktu    : $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "  App Dir  : $APP_DIR"
echo -e "  Service  : $SERVICE"
echo ""

# ── 0. Validasi .env ──────────────────────────────────────────────────────────
step "0/6 Memeriksa konfigurasi .env"
if [[ ! -f "$ENV_FILE" ]]; then
    [[ -f "$APP_DIR/backend/.env.example" ]] && \
        cp "$APP_DIR/backend/.env.example" "$ENV_FILE" && warn ".env dibuat dari .env.example" || \
        err ".env tidak ditemukan!"
fi

# Auto-generate JWT_SECRET jika kosong
if ! grep -qE "^(JWT_SECRET|SECRET_KEY)=.{8,}" "$ENV_FILE" 2>/dev/null; then
    warn "JWT_SECRET belum dikonfigurasi — auto-generating..."
    NEW_SECRET=$(openssl rand -hex 32)
    echo "" >> "$ENV_FILE"
    echo "JWT_SECRET=$NEW_SECRET" >> "$ENV_FILE"
    ok "JWT_SECRET di-generate"
fi
ok ".env valid"

# ── 1. Git Pull ───────────────────────────────────────────────────────────────
step "1/6 Pull update terbaru dari GitHub"
cd "$APP_DIR"

git fetch origin 2>/dev/null || warn "Tidak bisa fetch — lanjut dengan kode lokal"

LOCAL=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null || echo "")

if [[ -n "$LOCAL" && "$LOCAL" == "$REMOTE" ]]; then
    warn "Sudah up-to-date ($(git rev-parse --short HEAD))"
else
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || err "Git pull gagal"
    ok "Updated → $(git rev-parse --short HEAD): $(git log -1 --format='%s')"
fi

# ── 2. Python dependencies ────────────────────────────────────────────────────
step "2/6 Update Python dependencies"

# Support venv atau .venv
if [[ -d "$APP_DIR/backend/venv" ]]; then
    VENV="$APP_DIR/backend/venv"
elif [[ -d "$APP_DIR/backend/.venv" ]]; then
    VENV="$APP_DIR/backend/.venv"
else
    warn "venv tidak ditemukan — membuat baru..."
    python3.11 -m venv "$APP_DIR/backend/venv" 2>/dev/null || python3 -m venv "$APP_DIR/backend/venv"
    VENV="$APP_DIR/backend/venv"
fi

"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$APP_DIR/backend/requirements.txt" -q
ok "Python packages updated"

# ── 3. Build frontend ─────────────────────────────────────────────────────────
step "3/6 Build frontend (npm + Vite)"
cd "$APP_DIR/frontend"

# Install deps
if [[ -f "pnpm-lock.yaml" ]]; then
    pnpm install --silent 2>/dev/null || npm install --legacy-peer-deps
elif [[ -f "yarn.lock" ]]; then
    yarn install --silent 2>/dev/null || npm install --legacy-peer-deps
else
    npm install --legacy-peer-deps --prefer-offline 2>/dev/null || npm install --legacy-peer-deps
fi

# Build
CI=false npm run build

# Cek output (Vite → dist/, atau dikonfigurasi ke build/)
if [[ -f "dist/index.html" ]]; then
    ok "Frontend build selesai → dist/"
elif [[ -f "build/index.html" ]]; then
    ok "Frontend build selesai → build/"
else
    err "Build gagal — index.html tidak ditemukan di dist/ maupun build/"
fi

# ── 4. Update systemd service ─────────────────────────────────────────────────
step "4/6 Perbarui systemd service"

# Tentukan VENV_BIN
VENV_BIN="$VENV/bin/uvicorn"
[[ ! -f "$VENV_BIN" ]] && VENV_BIN="$(which uvicorn 2>/dev/null || echo uvicorn)"

cat > "/etc/systemd/system/${SERVICE}.service" <<SVCEOF
[Unit]
Description=NOC Sentinel v3 Backend (FastAPI/Uvicorn)
Documentation=https://github.com/afani-arba/noc-sentinel-v3
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=${VENV_BIN} server:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --loop asyncio \
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
systemctl enable "$SERVICE" --quiet

# Symlink untuk akses mudah
cp "$APP_DIR/update.sh" /usr/local/bin/noc-update 2>/dev/null || true
chmod +x /usr/local/bin/noc-update 2>/dev/null || true
ok "Systemd service diperbarui"

# ── 5. Restart service ────────────────────────────────────────────────────────
step "5/6 Restart backend service"
systemctl restart "$SERVICE"
sleep 4

if systemctl is-active --quiet "$SERVICE"; then
    ok "Backend '$SERVICE': RUNNING ✓"
else
    echo -e "${RED}✗ Backend gagal start! Error log:${NC}"
    journalctl -u "$SERVICE" -n 30 --no-pager
    warn "Cek: $ENV_FILE — pastikan JWT_SECRET dan MONGO_URI sudah benar"
    exit 1
fi

# Reload nginx
systemctl reload nginx 2>/dev/null && ok "Nginx di-reload" || true

# ── 6. Verifikasi & ringkasan ─────────────────────────────────────────────────
step "6/6 Verifikasi & Ringkasan"
sleep 2

# Health check
if curl -sf http://localhost:8000/api/health 2>/dev/null | grep -q "ok"; then
    ok "API health check: OK ✓"
else
    warn "API health tidak merespon (backend mungkin masih starting)"
fi

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗"
echo    "║                  ✅ UPDATE SELESAI!                          ║"
echo -e "╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Commit  :${NC} $(git -C $APP_DIR rev-parse --short HEAD 2>/dev/null) — $(git -C $APP_DIR log -1 --format='%s' 2>/dev/null)"
echo -e "  ${BOLD}Backend :${NC} $(systemctl is-active $SERVICE)"
echo -e "  ${BOLD}Nginx   :${NC} $(systemctl is-active nginx 2>/dev/null || echo 'n/a')"
echo -e "  ${BOLD}MongoDB :${NC} $(systemctl is-active mongod 2>/dev/null || echo 'n/a')"
echo ""
echo -e "  ${YELLOW}➡ Buka browser → Ctrl+Shift+R untuk melihat perubahan${NC}"
echo ""
