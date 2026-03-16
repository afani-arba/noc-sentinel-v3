#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║   NOC Sentinel v3 — Install/Update Script                               ║
# ║   CARA PAKAI: sudo bash /opt/noc-sentinel-v3/install.sh                ║
# ╚══════════════════════════════════════════════════════════════════════════╝
set -e

APP_DIR="/opt/noc-sentinel-v3"
SERVICE="ARBAMonitoring"
VENV="$APP_DIR/backend/venv"
[ -d "$APP_DIR/backend/.venv" ] && VENV="$APP_DIR/backend/.venv"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'; BOLD='\033[1m'
ok()   { echo -e "  ${G}✔ $*${N}"; }
warn() { echo -e "  ${Y}⚠ $*${N}"; }
err()  { echo -e "\n${R}${BOLD}✗ ERROR: $*${N}\n"; exit 1; }
step() { echo -e "\n${BOLD}${B}▶ $*${N}"; }

[[ $EUID -ne 0 ]] && err "Jalankan sebagai root: sudo bash install.sh"
[[ ! -d "$APP_DIR/.git" ]] && err "Direktori $APP_DIR tidak ditemukan. Clone dulu."

echo -e "\n${BOLD}${B}╔════════════════════════════════════════════╗${N}"
echo -e "${BOLD}${B}║     NOC Sentinel v3 — Install/Update       ║${N}"
echo -e "${BOLD}${B}╚════════════════════════════════════════════╝${N}"
echo -e "  Waktu  : $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "  Commit : $(git -C $APP_DIR rev-parse --short HEAD 2>/dev/null || echo '?')"

# ── STEP 1: Stop ─────────────────────────────────────────────────────────────
step "[1/5] Stop Backend..."
systemctl stop "$SERVICE" 2>/dev/null || true
sleep 3
set +e; fuser -k 8000/tcp 2>/dev/null; set -e
ok "Backend stopped"

# ── STEP 2: Git Pull ──────────────────────────────────────────────────────────
step "[2/5] Git Pull..."
cd "$APP_DIR"
BEFORE=$(git rev-parse --short HEAD)
git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || warn "Git pull gagal — lanjut dengan kode lokal"
AFTER=$(git rev-parse --short HEAD)
[[ "$BEFORE" != "$AFTER" ]] && ok "Updated: $BEFORE → $AFTER ($(git log -1 --format='%s'))" || warn "Tidak ada update (commit: $AFTER)"

# ── STEP 3: Python packages ────────────────────────────────────────────────────
step "[3/5] Python packages + pysnmp..."

[[ ! -f "$VENV/bin/pip" ]] && python3 -m venv "$VENV" && ok "venv dibuat"

"$VENV/bin/pip" install --upgrade pip -q

# Hapus pysnmp lama yang konflik sebelum install
"$VENV/bin/pip" uninstall pysnmp pysnmp-lextudio -y -q 2>/dev/null || true

# Install semua dari requirements.txt (termasuk pysnmp-lextudio>=6.0.0)
"$VENV/bin/pip" install -r "$APP_DIR/backend/requirements.txt" -q

# Verifikasi pysnmp bisa diimport
if "$VENV/bin/python" -c "from pysnmp.hlapi import SnmpEngine, nextCmd; print('OK')" 2>/dev/null | grep -q "OK"; then
    VER=$("$VENV/bin/python" -c "import pysnmp; print(getattr(pysnmp,'__version__','?'))" 2>/dev/null || echo "?")
    ok "pysnmp $VER — import OK ✓"
else
    warn "pysnmp gagal diimport! Coba paksa install lextudio..."
    "$VENV/bin/pip" install 'pysnmp-lextudio>=6.0.0' -q \
        && ok "pysnmp-lextudio berhasil ✓" \
        || warn "pysnmp gagal total — SNMP nonaktif"
fi

ok "Python packages selesai"

# ── STEP 4: Build Frontend ─────────────────────────────────────────────────────
step "[4/5] Build Frontend..."
cd "$APP_DIR/frontend"
npm install --legacy-peer-deps --prefer-offline -q 2>/dev/null || npm install --legacy-peer-deps -q
npm run build
[[ -f "build/index.html" ]] && ok "Frontend build OK" || err "Build frontend gagal"

# ── STEP 5: Start ──────────────────────────────────────────────────────────────
step "[5/5] Start Backend..."

ENV_FILE="$APP_DIR/backend/.env"
if [[ -f "$ENV_FILE" ]] && grep -q "^SYSLOG_PORT=514$" "$ENV_FILE" 2>/dev/null; then
    sed -i 's/^SYSLOG_PORT=514$/SYSLOG_PORT=5140/' "$ENV_FILE"
    ok ".env: SYSLOG_PORT 514 → 5140"
fi

systemctl daemon-reload
systemctl start "$SERVICE"
sleep 5

systemctl is-active --quiet "$SERVICE" \
    && ok "Backend '$SERVICE': RUNNING ✔" \
    || { journalctl -u "$SERVICE" -n 30 --no-pager; exit 1; }

systemctl reload nginx 2>/dev/null && ok "Nginx di-reload" || true

sleep 3
curl -sf http://localhost:8000/api/health 2>/dev/null | grep -q "ok" \
    && ok "API health: OK ✔" \
    || warn "API belum respond — cek: journalctl -u $SERVICE -f"

echo ""
echo -e "${G}${BOLD}╔════════════════════════════════════════════╗${N}"
echo -e "${G}${BOLD}║   ✅  INSTALL/UPDATE SELESAI!               ║${N}"
echo -e "${G}${BOLD}╚════════════════════════════════════════════╝${N}"
echo ""
echo -e "  Commit  : $(git -C $APP_DIR log -1 --format='%h — %s')"
echo -e "  Backend : $(systemctl is-active $SERVICE)"
echo -e "  Waktu   : $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo -e "  ${Y}Monitor SNMP:${N} journalctl -u $SERVICE -f | grep 'SNMP DEBUG'"
echo -e "  ${Y}Hard refresh:${N} Ctrl+Shift+R"
echo ""
