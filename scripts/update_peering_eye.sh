#!/bin/bash
# ============================================================
#  Sentinel Peering-Eye — One-Liner Update Script
#  Jalankan dari: /opt/noc-sentinel
#
#  Usage: sudo bash scripts/update_peering_eye.sh
# ============================================================

set -e

INSTALL_DIR="/opt/noc-sentinel"

echo "============================================================"
echo "  Sentinel Peering-Eye — Update"
echo "============================================================"

cd "${INSTALL_DIR}"

# 1. Pull latest code
echo "[1/3] Menarik kode terbaru dari GitHub..."
git pull

# 2. Restart Sentinel services
echo "[2/3] Restart sentinel services..."
systemctl restart sentinel-eye  2>/dev/null && echo "  sentinel-eye   ✓" || echo "  sentinel-eye - tidak aktif (skip)"
systemctl restart sentinel-bgp  2>/dev/null && echo "  sentinel-bgp   ✓" || echo "  sentinel-bgp  - tidak aktif (skip)"

# 3. Restart main NOC backend
echo "[3/3] Restart noc-sentinel backend..."
systemctl restart noc-sentinel  2>/dev/null && echo "  noc-sentinel   ✓" || echo "  noc-sentinel  - sudah dijalankan terpisah"

echo ""
echo "Status terkini:"
systemctl status sentinel-eye --no-pager -l 2>/dev/null | head -5 || true

echo ""
echo "============================================================"
echo "  UPDATE SELESAI!"
echo "  Log: journalctl -u sentinel-eye -f"
echo "============================================================"
