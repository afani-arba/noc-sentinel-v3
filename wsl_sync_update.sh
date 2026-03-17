#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  NOC Sentinel v3 — WSL Sync & Update Script                  ║
# ║  Menyalin kode dari E:\ (Windows) ke /opt/noc-sentinel-v3    ║
# ╚══════════════════════════════════════════════════════════════╝

set -e

SOURCE="/mnt/e/noc-sentinel-v3"
DEST="/opt/noc-sentinel-v3"
SERVICE="ARBAMonitoring"
VENV="$DEST/backend/venv"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"

if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Harap jalankan script ini dengan sudo: sudo bash wsl_sync_update.sh${NC}"
  exit 1
fi

echo -e "\n${GREEN}══ Memperbarui NOC Sentinel di WSL (/opt/noc-sentinel-v3) ══${NC}\n"

echo "▶ 1/5 Menyalin file dari Windows (Drive E) ke WSL..."
if [ ! -d "$SOURCE/backend" ]; then
    echo -e "${RED}Folder sumber $SOURCE tidak ditemukan! Pastikan drive E Anda ter-mount di WSL.${NC}"
    exit 1
fi

# Copy backend & frontend (rsync lebih efisien jika ada)
if command -v rsync >/dev/null 2>&1; then
    rsync -a --exclude '*venv*' --exclude '__pycache__' "$SOURCE/backend/" "$DEST/backend/"
    rsync -a --exclude 'node_modules' --exclude 'build' --exclude 'dist' "$SOURCE/frontend/" "$DEST/frontend/"
else
    cp -r "$SOURCE/backend/"* "$DEST/backend/"
    cp -r "$SOURCE/frontend/src" "$DEST/frontend/"
    cp -r "$SOURCE/frontend/public" "$DEST/frontend/"
    cp "$SOURCE/frontend/package.json" "$DEST/frontend/"
    cp "$SOURCE/frontend/vite.config.js" "$DEST/frontend/" 2>/dev/null || true
fi
echo -e "${GREEN}  ✓ File berhasil disalin (sinkronisasi dari lokal E: ke WSL)${NC}"

echo "▶ 2/5 Membersihkan file SNMP lama di WSL..."
rm -f "$DEST/backend/core/snmp_poller.py"
rm -f "$DEST/backend/core/snmp_compat.py"
echo -e "${GREEN}  ✓ File SNMP usang dihapus${NC}"

echo "▶ 3/5 Memperbarui Python Dependencies (Menghapus library SNMP)..."
[ -d "$DEST/backend/.venv" ] && VENV="$DEST/backend/.venv"
if [ -f "$VENV/bin/pip" ]; then
    "$VENV/bin/pip" uninstall pysnmp pysnmp-lextudio pysmi-lextudio pyasn1 pyasn1-modules -y -q 2>/dev/null || true
    "$VENV/bin/pip" install -r "$DEST/backend/requirements.txt" -q
else
    pip uninstall pysnmp pysnmp-lextudio pysmi-lextudio pyasn1 pyasn1-modules -y -q 2>/dev/null || true
    pip install -r "$DEST/backend/requirements.txt" -q
fi
echo -e "${GREEN}  ✓ Dependencies diperbarui${NC}"

echo "▶ 4/5 Build ulang Frontend React..."
cd "$DEST/frontend"
npm install --legacy-peer-deps -q
CI=false npm run build
echo -e "${GREEN}  ✓ Frontend berhasil dirender ulang (SNMP UI musnah)${NC}"

echo "▶ 5/5 Restart Service Backend..."
systemctl stop "$SERVICE" 2>/dev/null || true
sleep 2
fuser -k 8000/tcp 2>/dev/null || lsof -ti:8000 | xargs -r kill -9 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true
systemctl start "$SERVICE" 2>/dev/null || pm2 restart all 2>/dev/null || true
echo -e "${GREEN}  ✓ Service backend di-restart${NC}"

echo -e "\n${GREEN}Update Selesai! Silakan TEST API lagi di web.${NC}"
echo -e "${YELLOW}CATATAN PENTING: Lakukan Hard-refresh di browser (tekan CTRL + SHIFT + R) untuk menghapus cache memori browser Anda.${NC}\n"
