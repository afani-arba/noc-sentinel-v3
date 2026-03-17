#!/bin/bash
# ═══════════════════════════════════════════════════════════
# NOC Sentinel v3 — Update Script (Fitur v4)
# 4 Fitur baru: ISP Multi-Chart, Historical Compare, Backup Diff, PWA
# Jalankan: sudo bash update_features_v4.sh
# ═══════════════════════════════════════════════════════════
set -e
APP_DIR="/opt/noc-sentinel-v3"
FRONTEND_DIR="$APP_DIR/frontend"
SERVICE="nocsentinel"

echo "══════════════════════════════════════════"
echo "  NOC Sentinel v3 — Update Fitur v4"
echo "══════════════════════════════════════════"

# 1. Pull latest source
echo "[1/4] Pulling latest code from GitHub..."
cd "$APP_DIR"
git pull origin main

# 2. Rebuild frontend (karena ada perubahan DashboardPage.jsx, manifest.json, sw.js)
echo "[2/4] Rebuilding frontend (ISP chart + PWA)..."
cd "$FRONTEND_DIR"
npm install --silent
npm run build

# 3. Restart backend service
echo "[3/4] Restarting backend service..."
sudo systemctl restart "$SERVICE"

# 4. Verify
echo "[4/4] Checking service status..."
sleep 3
if systemctl is-active --quiet "$SERVICE"; then
    echo "✅ Service '$SERVICE' is running."
else
    echo "❌ Service '$SERVICE' failed to start. Check logs:"
    echo "   sudo journalctl -u $SERVICE -n 50 --no-pager"
    exit 1
fi

echo ""
echo "══════════════════════════════════════════"
echo "✅ Update selesai! Fitur yang aktif:"
echo "   • Dashboard > ISP per-Interface chart (jika multi-ISP)"
echo "   • Dashboard > Perbandingan Historis (today vs lalu)"
echo "   • Backups > /api/backups/diff?file_a=X&file_b=Y"
echo "   • PWA: bisa di-install di HP via browser (+ Push Notif)"
echo "══════════════════════════════════════════"
