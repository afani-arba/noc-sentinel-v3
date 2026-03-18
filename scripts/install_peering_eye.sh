#!/bin/bash
# ============================================================
#  Sentinel Peering-Eye — Ubuntu VPS Install Script
#  Run as root atau dengan sudo
#  One-liner: curl -sSL <url>/install_peering_eye.sh | sudo bash
# ============================================================
set -e

echo ""
echo "============================================================"
echo "  Sentinel Peering-Eye — Installer v1.0"
echo "  DNS Syslog + NetFlow + BGP Speaker"
echo "============================================================"
echo ""

# ── Config ──────────────────────────────────────────────────
# Auto-detect install dir (wherever this script is located)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
INSTALL_DIR="$(dirname "${SCRIPT_DIR}")"
PYTHON_BIN="python3"
GOBGP_VERSION="3.30.0"
GOBGP_URL="https://github.com/osrg/gobgp/releases/download/v${GOBGP_VERSION}/gobgp_${GOBGP_VERSION}_linux_amd64.tar.gz"
REPO_SCRIPTS="${INSTALL_DIR}/scripts"

echo "  Install Dir  : ${INSTALL_DIR}"
echo "  Scripts Dir  : ${REPO_SCRIPTS}"

# ── 0. Check root ────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
  echo "[ERROR] Script ini harus dijalankan sebagai root (sudo bash install_peering_eye.sh)"
  exit 1
fi

# ── 1. Update & install dependencies ─────────────────────────
echo "[1/7] Menginstall Python dependencies..."
apt-get update -q
apt-get install -y -q python3 python3-pip python3-venv curl wget tar jq

# ── 2. Install Python packages ────────────────────────────────
echo "[2/7] Menginstall Python packages untuk sentinel_eye.py..."
pip3 install --quiet pymongo

echo "      Python packages installed."

# ── 3. Install GoBGP ─────────────────────────────────────────
echo "[3/7] Menginstall GoBGP v${GOBGP_VERSION}..."
if command -v gobgp &>/dev/null; then
  echo "      GoBGP sudah terinstall: $(gobgp --version 2>&1 | head -1)"
else
  TMP_DIR=$(mktemp -d)
  wget -q "${GOBGP_URL}" -O "${TMP_DIR}/gobgp.tar.gz"
  tar -xzf "${TMP_DIR}/gobgp.tar.gz" -C "${TMP_DIR}"
  mv "${TMP_DIR}/gobgp"   /usr/local/bin/gobgp
  mv "${TMP_DIR}/gobgpd"  /usr/local/bin/gobgpd
  chmod +x /usr/local/bin/gobgp /usr/local/bin/gobgpd
  rm -rf "${TMP_DIR}"
  echo "      GoBGP installed: $(gobgp --version 2>&1 | head -1)"
fi

# ── 4. Copy scripts ───────────────────────────────────────────
echo "[4/7] Menyalin script ke ${REPO_SCRIPTS}..."
mkdir -p "${REPO_SCRIPTS}"
mkdir -p /etc/gobgp

# Script sudah ada di repo, cukup pastikan ada
if [ ! -f "${REPO_SCRIPTS}/sentinel_eye.py" ]; then
  echo "      [WARN] sentinel_eye.py tidak ditemukan di ${REPO_SCRIPTS}"
  echo "      Pastikan git pull sudah dilakukan di ${INSTALL_DIR}"
fi

if [ ! -f "${REPO_SCRIPTS}/sentinel_bgp.py" ]; then
  echo "      [WARN] sentinel_bgp.py tidak ditemukan di ${REPO_SCRIPTS}"
fi

# ── 5. Create env file ────────────────────────────────────────
echo "[5/7] Membuat environment file..."
ENV_FILE="/etc/noc-sentinel/peering-eye.env"
mkdir -p /etc/noc-sentinel
if [ ! -f "${ENV_FILE}" ]; then
  cat > "${ENV_FILE}" << 'ENVEOF'
# Sentinel Peering-Eye Environment Variables
MONGO_URL=mongodb://localhost:27017
MONGO_DB=noc_sentinel
DNS_SYSLOG_PORT=5514
NETFLOW_PORT=2055
FLUSH_INTERVAL=60
LOCAL_AS=65000
BGP_SYNC_INTERVAL=300
ENVEOF
  echo "      Env file created at ${ENV_FILE}"
  echo "      EDIT FILE INI sebelum menjalankan service!"
else
  echo "      Env file sudah ada: ${ENV_FILE} (tidak ditimpa)"
fi

# ── 6. Create systemd services ────────────────────────────────
echo "[6/7] Membuat systemd service..."

# sentinel-eye.service
cat > /etc/systemd/system/sentinel-eye.service << SVCEOF
[Unit]
Description=Sentinel Peering-Eye DNS+NetFlow Collector
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${PYTHON_BIN} ${REPO_SCRIPTS}/sentinel_eye.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=sentinel-eye

[Install]
WantedBy=multi-user.target
SVCEOF

# sentinel-bgp.service
cat > /etc/systemd/system/sentinel-bgp.service << SVCEOF
[Unit]
Description=Sentinel Peering-Eye BGP Speaker
After=network.target mongod.service sentinel-eye.service

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${PYTHON_BIN} ${REPO_SCRIPTS}/sentinel_bgp.py
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=sentinel-bgp

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable sentinel-eye sentinel-bgp
echo "      Services enabled (belum distart, tunggu konfigurasi selesai)"

# ── 7. Print Mikrotik configuration instructions ──────────────
echo ""
echo "[7/7] Konfigurasi Mikrotik yang diperlukan:"
echo ""

UBUNTU_IP=$(ip route get 1 2>/dev/null | head -1 | awk '{print $7}')

echo "============================================================"
echo "  COPY perintah berikut ke setiap Mikrotik:"
echo "============================================================"
echo ""
echo "# Step 1: Aktifkan DNS di Mikrotik"
echo "/ip dns set allow-remote-requests=yes"
echo ""
echo "# Step 2: Buat logging action ke Ubuntu VPS (DNS Syslog)"
echo "/system logging action add name=sentinel-dns target=remote remote=${UBUNTU_IP} remote-port=5514 src-address=0.0.0.0"
echo ""
echo "# Step 3: Enable DNS logging"
echo "/system logging add topics=dns action=sentinel-dns"
echo ""
echo "# Step 4: Aktifkan NetFlow/Traffic-Flow ke Ubuntu VPS"
echo "/ip traffic-flow set enabled=yes"
echo "/ip traffic-flow target add dst-address=${UBUNTU_IP} port=2055 version=5"
echo ""
echo "# Step 5: BGP Peering (Opsional — untuk Sentinel BGP Speaker)"
echo "/routing bgp instance add as=65001 router-id=<MIKROTIK_IP>"
echo "/routing bgp peer add name=sentinel-ubuntu remote-address=${UBUNTU_IP} remote-as=65000"
echo ""
echo "============================================================"
echo ""
echo "Setelah semua Mikrotik dikonfigurasi, start services:"
echo "  sudo systemctl start sentinel-eye"
echo "  sudo systemctl start sentinel-bgp  # (opsional jika pakai BGP)"
echo ""
echo "Cek logs:"
echo "  sudo journalctl -u sentinel-eye -f"
echo "  sudo journalctl -u sentinel-bgp -f"
echo ""
echo "============================================================"
echo "  INSTALASI SELESAI!"
echo "============================================================"
