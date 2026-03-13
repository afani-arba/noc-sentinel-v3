#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — Update Script
# Fix: Traffic History ISP-aware (Dashboard & DeviceDetail)
# Jalankan: sudo bash update_traffic_history.sh
# =============================================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

APP_DIR="/opt/noc-sentinel-v3"
SERVICE="nocsentinel"

[[ $EUID -ne 0 ]] && echo -e "${RED}Jalankan dengan: sudo bash update_traffic_history.sh${NC}" && exit 1

echo -e "${BOLD}${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   NOC Sentinel v3 — Update Traffic History ISP-Aware         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. Git Pull ───────────────────────────────────────────────────────────────
echo -e "${YELLOW}→ [1/3] Pull update dari GitHub...${NC}"
cd "$APP_DIR"
git pull origin main
echo -e "${GREEN}✓ Code updated: $(git log -1 --format='%h %s')${NC}"

# ── 2. Restart service (perubahan hanya backend, tidak perlu build frontend) ──
echo -e "${YELLOW}→ [2/3] Restart backend service...${NC}"
systemctl restart "$SERVICE"
sleep 3

# ── 3. Verifikasi ─────────────────────────────────────────────────────────────
echo -e "${YELLOW}→ [3/3] Verifikasi...${NC}"
if systemctl is-active --quiet "$SERVICE"; then
    echo -e "${GREEN}✓ $SERVICE: RUNNING${NC}"
else
    echo -e "${RED}✗ Service gagal start!${NC}"
    journalctl -u "$SERVICE" -n 20 --no-pager
    exit 1
fi

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗"
echo    "║  ✅ UPDATE SELESAI! Perubahan:                                ║"
echo    "║  • Traffic History Dashboard: hanya tampil data ISP          ║"
echo    "║  • Multi-ISP: akumulasi dari semua interface (ISP1+ISP2+...) ║"
echo    "║  • Device tanpa comment ISP: fallback sum interface fisik    ║"
echo -e "╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${YELLOW}➡ Buka Dashboard → Ctrl+Shift+R untuk melihat data terbaru${NC}"
echo -e "  ${YELLOW}➡ Data lama di grafik masih dari sebelum update (belum ada isp_bandwidth)${NC}"
echo -e "  ${YELLOW}➡ Data baru (setelah polling berikutnya ~30 detik) langsung akurat${NC}"
echo ""
