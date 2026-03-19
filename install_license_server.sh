#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  NOC Sentinel License Server - 1-Click Installer             ║
# ║  Cara pakai: sudo bash install_license_server.sh             ║
# ╚══════════════════════════════════════════════════════════════╝
set -e

APP_DIR="/opt/noc-sentinel-v3/license-server"
BACKEND_DIR="$APP_DIR/backend"
SERVICE_NAME="NOCLicenseServer"
VENV="$BACKEND_DIR/venv"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"

echo -e "\n${GREEN}══ Instalasi NOC Sentinel License Server ══${NC}\n"

echo "▶ 1. Menyiapkan Folder & Virtual Environment Python..."
mkdir -p "$BACKEND_DIR"
cd "$BACKEND_DIR"

if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi

echo "▶ 2. Menginstall Python Dependencies..."
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$BACKEND_DIR/requirements.txt" -q

echo "▶ 3. Membuat Systemd Service untuk menjalankan di Background..."
cat <<EOF > /etc/systemd/system/${SERVICE_NAME}.service
[Unit]
Description=NOC Sentinel License Server (FastAPI)
After=network.target

[Service]
User=root
WorkingDirectory=$BACKEND_DIR
Environment="PATH=$VENV/bin"
ExecStart=$VENV/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "▶ 4. Menjalankan Service..."
systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME

echo -e "\n${GREEN}✅ NOC License Server berhasil diinstall dan dijalankan!${NC}"
echo "▶ Server Lisensi berjalan pada port 1744 secara otomatis."
echo "▶ Anda bisa mengakses UI Dashboard Server Lisensi di: http://103.217.217.36:1744"
echo "▶ Cek log service dengan: journalctl -fu $SERVICE_NAME"
