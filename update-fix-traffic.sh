#!/bin/bash
# Script Update Cepat untuk Fix Trafik Identik
# Karena perubahan hanya ada di backend (Python), proses update
# tidak perlu melakukan build frontend (npm run build).

APP_DIR="/opt/noc-sentinel-v3"
SERVICE_NAME="nocsentinel" # Atur ke ARBAMonitoring jika service berbeda

echo "================================================="
echo "🔄 Memulai Update Fix Bandwidth / Trafik Identik..."
echo "================================================="

cd $APP_DIR || { echo "❌ Direktori $APP_DIR tidak ditemukan!"; exit 1; }

echo "[1/2] Menarik pembaruan terbaru dari GitHub..."
git pull origin main || { echo "❌ Gagal melakukan git pull"; exit 1; }
echo "✅ Repositori berhasil diperbarui."

echo "[2/2] Me-restart service backend..."
# Cek nama service yang digunakan
if systemctl list-unit-files | grep -q "ARBAMonitoring.service"; then
    SERVICE_NAME="ARBAMonitoring"
fi

systemctl daemon-reload
systemctl restart $SERVICE_NAME

if [ $? -eq 0 ]; then
    echo "✅ Service backend ($SERVICE_NAME) berhasil direstart."
else
    echo "❌ Gagal me-restart service backend. Silakan periksa log."
    exit 1
fi

echo "================================================="
echo "🎉 Update Selesai! Bug trafik identik telah diperbaiki."
echo "Silakan lihat perubahan di Dashboard atau Wall Display."
echo "================================================="
