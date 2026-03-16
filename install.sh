#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║   NOC Sentinel v3 — Install/Update Script                               ║
# ║   Fix: SNMP 0 interfaces (root cause: pysnmp sync/async type mismatch)  ║
# ║                                                                          ║
# ║   CARA PAKAI (di server):                                               ║
# ║     sudo bash /opt/noc-sentinel-v3/install.sh                          ║
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
echo ""

# ── STEP 1: Stop service ────────────────────────────────────────────────────
step "[1/5] Stop Backend..."
systemctl stop "$SERVICE" 2>/dev/null || true
i=0
while systemctl is-active --quiet "$SERVICE" 2>/dev/null && [[ $i -lt 15 ]]; do
    sleep 1; i=$((i+1))
done
set +e
PIDS=$(lsof -ti:8000 2>/dev/null)
[[ -n "$PIDS" ]] && kill -9 $PIDS 2>/dev/null
fuser -k 8000/tcp 2>/dev/null
set -e
ok "Backend stopped"

# ── STEP 2: Git Pull ────────────────────────────────────────────────────────
step "[2/5] Git Pull..."
cd "$APP_DIR"
BEFORE=$(git rev-parse --short HEAD)
git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || warn "Git pull gagal — lanjut dengan kode lokal"
AFTER=$(git rev-parse --short HEAD)
if [[ "$BEFORE" == "$AFTER" ]]; then
    warn "Tidak ada update baru (commit: $AFTER)"
else
    ok "Updated: $BEFORE → $AFTER"
    echo "  Perubahan: $(git log -1 --format='%s')"
fi

# ── STEP 3: Python packages + pysnmp fix ───────────────────────────────────
step "[3/5] Python packages + pysnmp..."

# Buat/aktifkan venv jika belum ada
if [[ ! -f "$VENV/bin/pip" ]]; then
    warn "venv belum ada, buat baru..."
    python3 -m venv "$VENV"
    ok "venv dibuat di $VENV"
fi

"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$APP_DIR/backend/requirements.txt" -q

# ── KRITIS: pysnmp fix ──────────────────────────────────────────────────────
# v3 pakai pysnmp>=7.x dengan snmp_compat bridge yang import dari v3arch.sync
# Hapus pysnmp-lextudio jika ada (konflik!) lalu install pysnmp>=7
echo ""
echo -e "  ${B}► Verifikasi pysnmp sync module...${N}"

# Tes apakah pysnmp.hlapi.v3arch.sync tersedia (kunci fix!)
if "$VENV/bin/python" -c "from pysnmp.hlapi.v3arch.sync import nextCmd, UdpTransportTarget; print('OK')" 2>/dev/null | grep -q "OK"; then
    VER=$("$VENV/bin/python" -c "import pysnmp; print(pysnmp.__version__)" 2>/dev/null || echo "?")
    ok "pysnmp $VER — v3arch.sync tersedia ✓"
else
    warn "pysnmp.hlapi.v3arch.sync tidak ada — reinstall pysnmp>=7..."
    "$VENV/bin/pip" uninstall pysnmp pysnmp-lextudio pysnmp-se -y -q 2>/dev/null || true
    "$VENV/bin/pip" install 'pysnmp>=7.0.0' -q \
        && ok "pysnmp 7.x berhasil diinstall ✓" \
        || {
            warn "pysnmp 7.x gagal, coba pysnmp-lextudio..."
            "$VENV/bin/pip" install 'pysnmp-lextudio>=1.1.0' -q \
                && ok "pysnmp-lextudio terinstall ✓" \
                || warn "Semua pysnmp gagal — SNMP nonaktif"
        }
fi

# Test snmp_compat bridge
if "$VENV/bin/python" -c "
import sys; sys.path.insert(0, '$APP_DIR/backend')
from snmp_compat import PYSNMP_AVAILABLE, PYSNMP_VERSION
print(f'snmp_compat OK: v={PYSNMP_VERSION} available={PYSNMP_AVAILABLE}')
" 2>/dev/null | grep -q "OK"; then
    STATUS=$("$VENV/bin/python" -c "
import sys; sys.path.insert(0,'$APP_DIR/backend')
from snmp_compat import PYSNMP_VERSION; print(PYSNMP_VERSION)
" 2>/dev/null)
    ok "snmp_compat bridge OK (pysnmp v$STATUS)"
else
    warn "snmp_compat bridge gagal — SNMP mungkin nonaktif"
fi

ok "Python packages selesai"

# ── STEP 4: Build Frontend ──────────────────────────────────────────────────
step "[4/5] Build Frontend..."
cd "$APP_DIR/frontend"
npm install --legacy-peer-deps --prefer-offline -q 2>/dev/null || npm install --legacy-peer-deps -q
npm run build
[[ -f "build/index.html" ]] && ok "Frontend build OK" || err "Build frontend gagal"

# ── STEP 5: Start Backend ───────────────────────────────────────────────────
step "[5/5] Start Backend..."

# Fix SYSLOG_PORT kalau masih 514
ENV_FILE="$APP_DIR/backend/.env"
if [[ -f "$ENV_FILE" ]] && grep -q "^SYSLOG_PORT=514$" "$ENV_FILE" 2>/dev/null; then
    sed -i 's/^SYSLOG_PORT=514$/SYSLOG_PORT=5140/' "$ENV_FILE"
    ok ".env: SYSLOG_PORT 514 → 5140"
fi

systemctl daemon-reload
systemctl start "$SERVICE"
sleep 5

if systemctl is-active --quiet "$SERVICE"; then
    ok "Backend '$SERVICE': RUNNING ✔"
else
    echo -e "${R}✗ Backend gagal start! Log:${N}"
    journalctl -u "$SERVICE" -n 30 --no-pager
    exit 1
fi

systemctl reload nginx 2>/dev/null && ok "Nginx di-reload" || true

# ── Health check ─────────────────────────────────────────────────────────────
sleep 3
if curl -sf http://localhost:8000/api/health 2>/dev/null | grep -q "ok"; then
    ok "API health: OK ✔"
else
    warn "API belum respond — cek: journalctl -u $SERVICE -f"
fi

# ── Selesai ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${G}${BOLD}╔════════════════════════════════════════════╗${N}"
echo -e "${G}${BOLD}║   ✅  INSTALL/UPDATE SELESAI!               ║${N}"
echo -e "${G}${BOLD}╚════════════════════════════════════════════╝${N}"
echo ""
echo -e "  Commit  : $(git -C $APP_DIR log -1 --format='%h — %s')"
echo -e "  Backend : $(systemctl is-active $SERVICE)"
echo -e "  Waktu   : $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo -e "  ${Y}Monitor SNMP realtime:${N}"
echo -e "  ${B}journalctl -u $SERVICE -f | grep 'SNMP DEBUG'${N}"
echo ""
echo -e "  ${Y}Hard refresh browser: Ctrl+Shift+R${N}"
echo ""
