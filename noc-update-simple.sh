#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  NOC Sentinel v3 — Simple Update Script                     ║
# ║  Usage: sudo bash noc-update-simple.sh                      ║
# ╚══════════════════════════════════════════════════════════════╝
set -e

APP_DIR="/opt/noc-sentinel-v3"
SERVICE="ARBAMonitoring"
VENV="$APP_DIR/backend/venv"
[ -d "$APP_DIR/backend/.venv" ] && VENV="$APP_DIR/backend/.venv"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
ok()   { echo -e "${GREEN}  ✓ $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${NC}"; }
err()  { echo -e "${RED}  ✗ $*${NC}"; exit 1; }

echo -e "\n${GREEN}══ NOC Sentinel v3 Quick Update ══${NC}\n"

# ── 1. Git pull ──────────────────────────────────────────────────
echo "▶ 1/5  Git pull..."
cd "$APP_DIR"
git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || err "Git pull gagal"
ok "Code updated → $(git rev-parse --short HEAD): $(git log -1 --format='%s')"

# ── 2. Python deps ───────────────────────────────────────────────
echo "▶ 2/5  Install Python packages..."
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$APP_DIR/backend/requirements.txt" -q

# Pastikan pysnmp-lextudio ada (SNMP Monitoring dependency)
if ! "$VENV/bin/python" -c "import pysnmp" 2>/dev/null; then
    warn "pysnmp belum ada — install pysnmp-lextudio..."
    "$VENV/bin/pip" install 'pysnmp-lextudio>=1.1.0' -q \
        && ok "pysnmp-lextudio terinstall" \
        || warn "pysnmp gagal install (fitur Test SNMP nonaktif)"
else
    ok "pysnmp tersedia"
fi
ok "Python packages OK"

# ── 3. Build frontend ────────────────────────────────────────────
echo "▶ 3/5  Build frontend..."
cd "$APP_DIR/frontend"
npm install --legacy-peer-deps --prefer-offline -q 2>/dev/null || npm install --legacy-peer-deps -q
CI=false npm run build
[ -f "build/index.html" ] && ok "Frontend build OK" || { [ -f "dist/index.html" ] && ok "Frontend build OK (dist/)" || err "Build frontend gagal"; }

# ── 4. Restart backend ───────────────────────────────────────────
echo "▶ 4/5  Restart backend..."
systemctl stop "$SERVICE" 2>/dev/null || true

# Tunggu proses berhenti (max 20 detik)
i=0
while systemctl is-active --quiet "$SERVICE" 2>/dev/null && [ $i -lt 20 ]; do
    sleep 1; i=$((i+1))
done

# Bebaskan port 8000
fuser -k 8000/tcp 2>/dev/null || lsof -ti:8000 | xargs -r kill -9 2>/dev/null || true
sleep 1

systemctl daemon-reload
systemctl start "$SERVICE"
sleep 5

if systemctl is-active --quiet "$SERVICE"; then
    ok "Backend RUNNING ✓"
else
    echo -e "${RED}Backend gagal start! Log terakhir:${NC}"
    journalctl -u "$SERVICE" -n 20 --no-pager
    exit 1
fi

# Reload nginx
systemctl reload nginx 2>/dev/null && ok "Nginx di-reload" || true

# ── 5. Health check ──────────────────────────────────────────────
echo "▶ 5/5  Health check..."
sleep 3
if curl -sf http://localhost:8000/api/health 2>/dev/null | grep -q "ok"; then
    ok "API health check: OK ✓"
else
    warn "API belum respond (mungkin masih starting, cek: journalctl -u $SERVICE -f)"
fi

echo -e "\n${GREEN}══ Update selesai! ══${NC}"
echo    "  Versi: $(cd $APP_DIR && git log -1 --format='%h %s')"
echo    "  Waktu: $(date '+%Y-%m-%d %H:%M:%S')"
