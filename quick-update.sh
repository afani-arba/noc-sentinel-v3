#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — Quick Update Script
# Untuk update cepat: git pull + build frontend + restart backend
# Jalankan: sudo bash quick-update.sh
# =============================================================================

set -e
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'; BOLD='\033[1m'
ok()   { echo -e "  ${G}✓ $1${N}"; }
warn() { echo -e "  ${Y}⚠ $1${N}"; }
err()  { echo -e "\n${R}${BOLD}✗ ERROR: $1${N}\n"; exit 1; }

APP_DIR="/opt/noc-sentinel-v3"
SERVICE="nocsentinel"

[[ $EUID -ne 0 ]] && err "Jalankan sebagai root: sudo bash quick-update.sh"
[[ ! -d "$APP_DIR/.git" ]] && err "Direktori $APP_DIR tidak ditemukan"

echo -e "\n${BOLD}${B}══════════════════════════════════════════${N}"
echo -e "${BOLD}   NOC Sentinel v3 — Quick Update${N}"
echo -e "${BOLD}${B}══════════════════════════════════════════${N}"
echo -e "  Waktu: $(date '+%Y-%m-%d %H:%M:%S WIB')"
echo ""

# ── 1. Git Pull ──────────────────────────────────────────────────────────────
echo -e "${BOLD}[1/3] Git Pull...${N}"
cd "$APP_DIR"
BEFORE=$(git rev-parse --short HEAD)
git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || warn "Git pull gagal — lanjut dengan kode lokal"
AFTER=$(git rev-parse --short HEAD)

if [[ "$BEFORE" == "$AFTER" ]]; then
    warn "Tidak ada perubahan dari GitHub (commit: $AFTER)"
else
    ok "Updated: $BEFORE → $AFTER  ($(git log -1 --format='%s'))"
fi

# ── 2. Build Frontend ────────────────────────────────────────────────────────
echo -e "\n${BOLD}[2/3] Build Frontend...${N}"
cd "$APP_DIR/frontend"
npm install --legacy-peer-deps --prefer-offline -q 2>/dev/null || npm install --legacy-peer-deps -q
npm run build

[[ ! -f "build/index.html" ]] && err "Build gagal — build/index.html tidak ditemukan"
ok "Frontend build selesai → build/"

# ── 3. Restart Backend ───────────────────────────────────────────────────────
echo -e "\n${BOLD}[3/3] Restart Backend...${N}"
systemctl restart "$SERVICE"
sleep 3

if systemctl is-active --quiet "$SERVICE"; then
    ok "Backend '$SERVICE': RUNNING ✓"
else
    echo -e "${R}✗ Backend gagal start!${N}"
    journalctl -u "$SERVICE" -n 20 --no-pager
    exit 1
fi

# Reload nginx jika ada
systemctl reload nginx 2>/dev/null && ok "Nginx di-reload" || true

# ── Selesai ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${G}${BOLD}══════════════════════════════════════════${N}"
echo -e "${G}${BOLD}  ✅ UPDATE SELESAI!${N}"
echo -e "${G}${BOLD}══════════════════════════════════════════${N}"
echo ""
echo -e "  Commit  : $(git -C $APP_DIR rev-parse --short HEAD) — $(git -C $APP_DIR log -1 --format='%s')"
echo -e "  Backend : $(systemctl is-active $SERVICE)"
echo ""
echo -e "  ${Y}➡ Ctrl+Shift+R di browser untuk melihat perubahan${N}"
echo ""
