#!/bin/bash
# ==============================================================
# Skrip Pembaruan Khusus NOC License Server
# ==============================================================

echo "Memulai proses update NOC License Server..."

# Pindah ke direktori license server (Sesuaikan path jika berbeda)
cd /root/noc-sentinel-license-server || { echo "[ERROR] Direktori /root/noc-sentinel-license-server tidak ditemukan!"; exit 1; }

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
# Sesuaikan nama service PM2 jika Anda menggunakan nama yang berbeda saat setup awal
pm2 restart noc-license-server || pm2 restart license-server || systemctl restart noc-license

echo "=============================================================="
echo "UPDATE SELESAI! NOC License Server berhasil diperbarui."
echo "=============================================================="
