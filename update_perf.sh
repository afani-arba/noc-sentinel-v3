#!/bin/bash
# ----------------------------------------------------
# Update Script for NOC Sentinel v3
# Fitur: Wall Display Performance Optimization
# ----------------------------------------------------
set -e

echo "Mengambil update terbaru dari GitHub..."
git pull origin main

echo "Update berhasil diunduh. Me-restart layanan Backend..."
sudo systemctl restart noc-sentinel-backend

echo "Selesai! NOC Sentinel Wall Display telah dioptimasi."
