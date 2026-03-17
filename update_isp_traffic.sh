#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — Quick Update Script
# Untuk update: fix ISP traffic detection (isp_bandwidth, keyword ISP1-20)
# Jalankan: sudo bash update_isp_traffic.sh
# =============================================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

APP_DIR="/opt/noc-sentinel-v3"
SERVICE="nocsentinel"

[[ $EUID -ne 0 ]] && echo -e "${RED}Jalankan dengan: sudo bash update_isp_traffic.sh${NC}" && exit 1

echo -e "${BOLD}${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   NOC Sentinel v3 — Update ISP Traffic Detection             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. Git Pull ───────────────────────────────────────────────────────────────
echo -e "${YELLOW}→ [1/4] Pull update dari GitHub...${NC}"
cd "$APP_DIR"
git pull origin main
echo -e "${GREEN}✓ Code updated: $(git log -1 --format='%h %s')${NC}"

# ── 2. Build frontend (badge ISP di DeviceDetailPage) ────────────────────────
echo -e "${YELLOW}→ [2/4] Build frontend...${NC}"
cd "$APP_DIR/frontend"
npm install --legacy-peer-deps --silent
npm run build
echo -e "${GREEN}✓ Frontend built${NC}"

# ── 3. Restart service ────────────────────────────────────────────────────────
echo -e "${YELLOW}→ [3/4] Restart backend service...${NC}"
systemctl restart "$SERVICE"
sleep 3

# ── 4. Verifikasi ─────────────────────────────────────────────────────────────
echo -e "${YELLOW}→ [4/4] Verifikasi...${NC}"
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
echo    "║  • Keyword ISP: ISP1-ISP20, WAN1-20, INPUT1-20 (dikunci)     ║"
echo    "║  • Traffic DL/UL hanya dari interface ISP (lebih akurat)      ║"
echo    "║  • Multi-ISP: support sampai 20 sumber internet               ║"
echo    "║  • Badge ISP di Device Detail page                            ║"
echo -e "╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${YELLOW}➡ Buka browser → Ctrl+Shift+R untuk melihat perubahan${NC}"
echo -e "  ${YELLOW}➡ Tambah komentar 'ISP1' / 'WAN' / 'INPUT' di interface MikroTik${NC}"
echo ""
