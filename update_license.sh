#!/bin/bash
# ==============================================================
# Skrip Pembaruan Khusus NOC License Server
# ==============================================================

echo "Memulai proses update NOC License Server..."

# Mencari direktori license server secara otomatis
if [ -d "license-server" ]; then
    cd license-server || exit 1
elif [ -d "/opt/noc-sentinel-license-server" ]; then
    cd /opt/noc-sentinel-license-server || exit 1
elif [ -d "/root/noc-sentinel-license-server" ]; then
    cd /root/noc-sentinel-license-server || exit 1
elif [ -d "../noc-sentinel-license-server" ]; then
    cd ../noc-sentinel-license-server || exit 1
else
    echo "[ERROR] Direktori noc-sentinel-license-server tidak ditemukan!"
    exit 1
fi

echo "1. Menarik update terbaru dari GitHub..."
git pull origin main

echo "2. Mengaktifkan Virtual Environment dan Update Dependencies..."
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "backend/venv" ]; then
    source backend/venv/bin/activate
fi

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
elif [ -f "backend/requirements.txt" ]; then
    pip install -r backend/requirements.txt
fi

echo "3. Merestart Service NOC License Server..."
if command -v pm2 &> /dev/null; then
    pm2 restart noc-license-server || pm2 restart license-server
fi
systemctl restart NOCLicenseServer || systemctl restart noc-license

echo "=============================================================="
echo "UPDATE SELESAI! NOC License Server berhasil diperbarui."
echo "=============================================================="
