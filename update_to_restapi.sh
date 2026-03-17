#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  NOC Sentinel v3 — REST API Native Update Script             ║
# ║  Usage: sudo bash update_to_restapi.sh                       ║
# ╚══════════════════════════════════════════════════════════════╝
set -e

APP_DIR="/opt/noc-sentinel-v3"
# Sesuaikan jika nama service anda berbeda
SERVICE="ARBAMonitoring" 
VENV="$APP_DIR/backend/venv"
[ -d "$APP_DIR/backend/.venv" ] && VENV="$APP_DIR/backend/.venv"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
ok()   { echo -e "${GREEN}  ✓ $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${NC}"; }
err()  { echo -e "${RED}  ✗ $*${NC}"; exit 1; }

echo -e "\n${GREEN}══ NOC Sentinel v3 REST API Native Update ══${NC}\n"

# ── 1. Git pull ──────────────────────────────────────────────────
echo "▶ 1/5  Sikronisasi kode git..."
cd "$APP_DIR"
# Coba pull dari main atau master
git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || warn "Git pull gagal/dilewati (Mungkin menggunakan kode lokal)"

ok "Sync selesai"

# ── 2. Clean Up SNMP ─────────────────────────────────────────────
echo "▶ 2/5  Membersihkan file & library SNMP usang..."
rm -f "$APP_DIR/backend/core/snmp_poller.py"
rm -f "$APP_DIR/backend/core/snmp_compat.py"
ok "File SNMP script lama dihapus"

# Uninstall library snmp lama agar environment bersih
if [ -f "$VENV/bin/pip" ]; then
    "$VENV/bin/pip" uninstall pysnmp pysnmp-lextudio pysmi-lextudio pyasn1 pyasn1-modules -y -q 2>/dev/null || true
    ok "Library SNMP dependencies dibersihkan dari venv"
else
    warn "VENV tidak ditemukan di $VENV, mengasumsikan global environment"
    pip uninstall pysnmp pysnmp-lextudio pysmi-lextudio pyasn1 pyasn1-modules -y -q 2>/dev/null || true
fi

# ── 3. Python dep ────────────────────────────────────────────────
echo "▶ 3/5  Install/Update Python requirements..."
if [ -f "$VENV/bin/pip" ]; then
    "$VENV/bin/pip" install --upgrade pip -q
    "$VENV/bin/pip" install -r "$APP_DIR/backend/requirements.txt" -q
else
    pip install -r "$APP_DIR/backend/requirements.txt" -q
fi
ok "Python dependencies (REST API mode) terpasang"

# ── 4. Build Frontend ────────────────────────────────────────────
echo "▶ 4/5  Build ulang UI Frontend (tanpa opsi SNMP)..."
cd "$APP_DIR/frontend"
npm install --legacy-peer-deps --prefer-offline -q 2>/dev/null || npm install --legacy-peer-deps -q
CI=false npm run build
if [ -f "build/index.html" ]; then
    ok "Frontend build OK (build/)"
elif [ -f "dist/index.html" ]; then
    ok "Frontend build OK (dist/)"
else
    warn "Frontend build tidak ditemukan, abaikan jika anda memang tidak mem-build di VPS"
fi

# ── 5. Restart Service ───────────────────────────────────────────
echo "▶ 5/5  Restart service & Reload server..."
systemctl stop "$SERVICE" 2>/dev/null || true

# Tunggu proses berhenti dengan sabar
i=0
while systemctl is-active --quiet "$SERVICE" 2>/dev/null && [ $i -lt 15 ]; do
    sleep 1; i=$((i+1))
done

# Kill zombie procesess di port 8000 jika ada backend nyangkut
fuser -k 8000/tcp 2>/dev/null || lsof -ti:8000 | xargs -r kill -9 2>/dev/null || true
sleep 1

# Start ulang systemctl
systemctl daemon-reload 2>/dev/null || true
systemctl start "$SERVICE" 2>/dev/null || true

# Jika belum jalan / systemctl ga ada, fallback pm2 jika ada
if ! systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    warn "Systemd tidak aktif, mencoba PM2..."
    pm2 restart all 2>/dev/null || warn "PM2 juga tidak mendeteksi proses."
else
    ok "Sytemd Service $SERVICE Restarted"
fi

# Reload konfigurasi server web jika pakai nginx
systemctl reload nginx 2>/dev/null && ok "Nginx reload OK" || true

echo -e "\n${GREEN}══ Update REST API Selesai! ══${NC}"
echo "Aplikasi NOC Sentinel sekarang telah beralih menggunakan 100% MikroTik REST API."
echo "Silakan cek halaman Dashboard & Devices di App Anda."
