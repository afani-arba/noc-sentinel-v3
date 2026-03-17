#!/bin/bash
# ==============================================================================
# Skrip Update Otomatis NOC Sentinel v3
# ==============================================================================
# Pastikan skrip ini dijalankan didalam folder aplikasi, contoh (/opt/noc-sentinel-v3)
# dengan hak akses root atau sudo.

echo "================================================="
echo "🔄 Memulai Proses Update NOC Sentinel v3"
echo "================================================="

# 1. Update Repository
echo "[1/4] Mengambil pembaruan terbaru dari GitHub..."
git fetch origin main > /dev/null 2>&1
git reset --hard origin/main > /dev/null 2>&1
echo "✅ Repositori berhasil di-update."

# 2. Build Frontend
echo "[2/4] Melakukan build ulang frontend Vite..."
cd frontend || { echo "❌ Folder frontend tidak ditemukan!"; exit 1; }
npm install > /dev/null 2>&1
npm run build > /dev/null 2>&1
cd ..
echo "✅ Build frontend berhasil."

# 3. Restart Backend Service
echo "[3/4] Me-restart service backend (nocsentinel.service)..."
systemctl daemon-reload
systemctl restart nocsentinel
if [ $? -eq 0 ]; then
    echo "✅ Service backend berhasil direstart."
else
    echo "❌ Gagal me-restart systemd service 'nocsentinel'. Harap periksa statusnya!"
fi

# Selesai
echo "================================================="
echo "🎉 Update Selesai! Aplikasi sudah menggunakan versi terbaru."
echo "Silakan refresh browser Anda menggunakan kombinasi Ctrl + F5."
echo "================================================="
