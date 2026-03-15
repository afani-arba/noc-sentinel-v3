#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — One-Click Installer
# Target : Ubuntu 20.04 LTS (Focal Fossa) ✅ TESTED
#          Ubuntu 22.04 LTS (Jammy) — compatible
# Usage  : sudo bash install.sh
# Repo   : https://github.com/afani-arba/noc-sentinel-v3
# =============================================================================

set -e
set -o pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

print_step()  { echo -e "\n${BLUE}${BOLD}═══ $1 ═══${NC}"; }
print_ok()    { echo -e "  ${GREEN}✓ $1${NC}"; }
print_warn()  { echo -e "  ${YELLOW}⚠ $1${NC}"; }
print_info()  { echo -e "  ${CYAN}ℹ $1${NC}"; }
print_error() { echo -e "\n${RED}${BOLD}✗ ERROR: $1${NC}\n"; exit 1; }

# ── Konstanta ─────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/afani-arba/noc-sentinel-v3.git"
APP_DIR="/opt/noc-sentinel-v3"
MONGO_DB="nocsentinel"
MONGO_USER="nocsentinel"
SERVICE_NAME="nocsentinel"
SYSLOG_SERVICE="nocsentinel-syslog"
NGINX_CONF="/etc/nginx/sites-available/nocsentinel"

# ── Cek root ──────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && print_error "Jalankan sebagai root: sudo bash install.sh"

# ── Cek OS ────────────────────────────────────────────────────────────────────
OS_ID=$(lsb_release -si 2>/dev/null || echo "Unknown")
OS_VER=$(lsb_release -sr 2>/dev/null || echo "0")
OS_CODE=$(lsb_release -cs 2>/dev/null || echo "focal")

if [[ "$OS_ID" != "Ubuntu" ]]; then
    print_warn "Script ini didesain untuk Ubuntu. OS terdeteksi: $OS_ID"
fi

echo -e "${BOLD}${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       NOC Sentinel v3 — Installer untuk Ubuntu 20.04         ║"
echo "║          ARBA Network Monitoring System v3.0                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  OS: ${OS_ID} ${OS_VER} (${OS_CODE})"
echo -e "  Waktu: $(date '+%Y-%m-%d %H:%M:%S WIB')"
echo ""

# ── Input Konfigurasi ─────────────────────────────────────────────────────────
print_step "Konfigurasi Instalasi"
echo ""

read -rp  "  IP atau domain server   [contoh: 192.168.1.10 / monitoring.arba.co.id]: " SERVER_HOST
read -rsp "  Password MongoDB user '$MONGO_USER': " MONGO_PASS; echo
read -rsp "  Password admin pertama NOC Sentinel: " ADMIN_PASS; echo
read -rsp "  JWT Secret (Enter = auto-generate 64-char random): " JWT_SECRET; echo
read -rp  "  Port Syslog UDP [default: 5140, tekan Enter]: " SYSLOG_PORT
SYSLOG_PORT=${SYSLOG_PORT:-5140}

# Validasi input
[[ -z "$SERVER_HOST" ]] && print_error "IP/Domain server tidak boleh kosong"
[[ -z "$MONGO_PASS"  ]] && print_error "Password MongoDB tidak boleh kosong"
[[ -z "$ADMIN_PASS"  ]] && print_error "Password admin tidak boleh kosong"
[[ ${#ADMIN_PASS} -lt 8 ]] && print_error "Password admin minimal 8 karakter"

# Auto-generate JWT secret jika kosong
if [[ -z "$JWT_SECRET" ]]; then
    JWT_SECRET=$(openssl rand -hex 32)
    print_ok "JWT Secret auto-generated (64 karakter)"
fi

# URL-encode password untuk MongoDB URI
MONGO_PASS_ENCODED=$(python3 -c "
import urllib.parse, sys
print(urllib.parse.quote('${MONGO_PASS}', safe=''))
" 2>/dev/null || echo "${MONGO_PASS}")

echo ""
print_info "Konfigurasi:"
echo -e "    Server   : ${SERVER_HOST}"
echo -e "    App Dir  : ${APP_DIR}"
echo -e "    MongoDB  : ${MONGO_DB}@localhost"
echo -e "    Syslog   : UDP port ${SYSLOG_PORT}"
echo ""
read -rp "  Lanjutkan instalasi? [Y/n]: " CONFIRM
[[ "${CONFIRM,,}" == "n" ]] && exit 0

# =============================================================================
print_step "1/10 Update sistem & install dependencies dasar"
# =============================================================================
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq \
    curl wget git gnupg lsb-release ca-certificates \
    build-essential software-properties-common \
    nginx openssl net-tools iputils-ping \
    libssl-dev libffi-dev python3-dev pkg-config \
    certbot python3-certbot-nginx \
    ufw 2>/dev/null || true

print_ok "System packages installed"

# =============================================================================
print_step "2/10 Install MongoDB 6.x"
# =============================================================================
if ! command -v mongod &>/dev/null; then
    print_info "Menginstall MongoDB 6.0..."

    # Import MongoDB GPG key
    curl -fsSL https://www.mongodb.org/static/pgp/server-6.0.asc | \
        gpg --dearmor -o /usr/share/keyrings/mongodb-server-6.0.gpg 2>/dev/null

    # Gunakan focal untuk Ubuntu 20.04 dan 22.04 (jammy juga support focal repo MongoDB)
    MONGO_CODENAME="focal"
    [[ "$OS_CODE" == "jammy" ]] && MONGO_CODENAME="jammy"

    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu ${MONGO_CODENAME}/mongodb-org/6.0 multiverse" \
        | tee /etc/apt/sources.list.d/mongodb-org-6.0.list > /dev/null

    apt-get update -qq
    apt-get install -y -qq mongodb-org
    print_ok "MongoDB 6.0 installed"
else
    print_warn "MongoDB sudah ada: $(mongod --version 2>/dev/null | head -1)"
fi

# Start MongoDB
systemctl enable mongod --quiet 2>/dev/null || true
systemctl start mongod 2>/dev/null || true
sleep 3

# Cek apakah mongod running
if ! systemctl is-active --quiet mongod; then
    print_warn "MongoDB belum running, mencoba start lagi..."
    systemctl start mongod
    sleep 5
fi

# Buat user MongoDB (tanpa auth dulu)
MONGO_CHECK=$(mongosh --quiet --eval \
    "db.getSiblingDB('${MONGO_DB}').getUsers().users.filter(u => u.user === '${MONGO_USER}').length" \
    2>/dev/null || echo "0")

if [[ "$MONGO_CHECK" == "0" || -z "$MONGO_CHECK" ]]; then
    mongosh --quiet <<EOF
use admin
db.createUser({
  user: "root",
  pwd: "${MONGO_PASS}admin",
  roles: ["root"]
})
use ${MONGO_DB}
db.createUser({
  user: "${MONGO_USER}",
  pwd: "${MONGO_PASS}",
  roles: [{ role: "readWrite", db: "${MONGO_DB}" }]
})
EOF
    # Enable auth
    if ! grep -q "authorization: enabled" /etc/mongod.conf 2>/dev/null; then
        cat >> /etc/mongod.conf <<'MONGOEOF'

security:
  authorization: enabled
MONGOEOF
        systemctl restart mongod
        sleep 3
    fi
    print_ok "MongoDB user '${MONGO_USER}' dibuat & auth enabled"
else
    print_warn "MongoDB user '${MONGO_USER}' sudah ada"
fi

# =============================================================================
print_step "3/10 Install Python 3.11"
# =============================================================================
if ! command -v python3.11 &>/dev/null; then
    print_info "Menambah PPA deadsnakes untuk Python 3.11..."
    add-apt-repository ppa:deadsnakes/ppa -y > /dev/null 2>&1
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv python3.11-dev python3.11-distutils 2>/dev/null || \
    apt-get install -y -qq python3.11 python3.11-venv python3.11-dev

    # Install pip untuk python3.11
    if ! python3.11 -m pip --version &>/dev/null 2>&1; then
        curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 > /dev/null 2>&1
    fi
    print_ok "Python $(python3.11 --version) installed"
else
    print_warn "Python 3.11 sudah ada: $(python3.11 --version)"
fi

# =============================================================================
print_step "4/10 Install Node.js 20 LTS"
# =============================================================================
NODE_MAJOR=$(node --version 2>/dev/null | grep -oP '(?<=v)\d+' | head -1 || echo "0")
if [[ "$NODE_MAJOR" -lt 18 ]]; then
    print_info "Installing Node.js 20 LTS..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
    apt-get install -y -qq nodejs
    print_ok "Node.js $(node --version) installed"
else
    print_warn "Node.js $(node --version) sudah ada"
fi

# =============================================================================
print_step "5/10 Clone / Update repository"
# =============================================================================
if [[ -d "$APP_DIR/.git" ]]; then
    print_warn "Direktori $APP_DIR sudah ada — git pull..."
    cd "$APP_DIR"
    git remote set-url origin "$REPO_URL" 2>/dev/null || true
    git pull origin main
else
    print_info "Cloning repository..."
    git clone "$REPO_URL" "$APP_DIR"
fi
print_ok "Source code ready di $APP_DIR"

# =============================================================================
print_step "6/10 Setup Python Virtual Environment"
# =============================================================================
cd "$APP_DIR/backend"

if [[ ! -d "venv" ]]; then
    python3.11 -m venv venv
    print_ok "Virtual environment dibuat"
fi

source venv/bin/activate
pip install --upgrade pip setuptools wheel -q
pip install -r requirements.txt -q
deactivate
print_ok "Python packages terinstall"

# =============================================================================
print_step "7/10 Setup file konfigurasi .env"
# =============================================================================
ENV_FILE="$APP_DIR/backend/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$APP_DIR/backend/.env.example" "$ENV_FILE"

    # Konfigurasi MongoDB
    sed -i "s|mongodb://nocsentinel:GANTI_PASSWORD@localhost:27017/nocsentinel|mongodb://${MONGO_USER}:${MONGO_PASS_ENCODED}@localhost:27017/${MONGO_DB}|g" "$ENV_FILE"

    # JWT Secret
    sed -i "s|JWT_SECRET=GANTI_DENGAN_SECRET_KEY_ACAK_PANJANG|JWT_SECRET=${JWT_SECRET}|g" "$ENV_FILE"

    # CORS — allow server IP dan localhost
    sed -i "s|CORS_ORIGINS=http://localhost:3000|CORS_ORIGINS=http://${SERVER_HOST},http://${SERVER_HOST}:80,http://localhost:3000|g" "$ENV_FILE"

    # Syslog port
    sed -i "s|SYSLOG_PORT=5140|SYSLOG_PORT=${SYSLOG_PORT}|g" "$ENV_FILE"

    chmod 600 "$ENV_FILE"
    print_ok ".env berhasil dibuat dan dikonfigurasi"
else
    print_warn ".env sudah ada — tidak ditimpa"
    print_info "Pastikan JWT_SECRET dan MONGO_URI sesuai di $ENV_FILE"
fi

# =============================================================================
print_step "8/10 Build frontend (Vite + React)"
# =============================================================================
cd "$APP_DIR/frontend"

print_info "Menginstall npm packages (bisa butuh 3-5 menit)..."
npm install --legacy-peer-deps --prefer-offline 2>/dev/null || \
npm install --legacy-peer-deps

print_info "Building production bundle..."
npm run build

# Vite output ke 'build/' (dikonfigurasi di vite.config.js outDir: 'build')
if [[ ! -f "build/index.html" ]]; then
    print_error "Build gagal — build/index.html tidak ditemukan! Cek output npm run build di atas."
fi
print_ok "Frontend berhasil di-build → $APP_DIR/frontend/build/"

# =============================================================================
print_step "9/10 Konfigurasi Nginx"
# =============================================================================
# Hapus konfigurasi lama yang mungkin bentrok
rm -f /etc/nginx/sites-enabled/default
rm -f /etc/nginx/sites-enabled/noc-sentinel
rm -f /etc/nginx/sites-enabled/noc-sentinel-v3
rm -f /etc/nginx/sites-enabled/nocsentinel

cat > "$NGINX_CONF" <<NGINXEOF
server {
    listen 80;
    server_name ${SERVER_HOST} _;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml application/json application/javascript
               application/xml+rss application/atom+xml image/svg+xml;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Frontend (React SPA)
    root ${APP_DIR}/frontend/build;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # SSE Events — wajib buffering off agar real-time berjalan
    location /api/events/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 3600s;
        chunked_transfer_encoding on;
    }

    # API backend
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 30s;
        client_max_body_size 50M;
    }

    # Static asset caching
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|woff|woff2|ttf|svg|webp|map)\$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    access_log /var/log/nginx/nocsentinel_access.log;
    error_log  /var/log/nginx/nocsentinel_error.log warn;
}
NGINXEOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/nocsentinel

# Test konfigurasi nginx sebelum restart
nginx -t || print_error "Konfigurasi Nginx tidak valid! Cek: nginx -t"
systemctl restart nginx
systemctl enable nginx --quiet 2>/dev/null || true
print_ok "Nginx dikonfigurasi (SSE + SPA routing)"

# =============================================================================
print_step "10/10 Setup Systemd Service & Admin User"
# =============================================================================

# ── Backend service ───────────────────────────────────────────────────────────
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<SVCEOF
[Unit]
Description=NOC Sentinel v3 Backend (FastAPI/Uvicorn)
Documentation=https://github.com/afani-arba/noc-sentinel-v3
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=${APP_DIR}/backend/venv/bin/uvicorn server:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --loop asyncio \
    --access-log \
    --log-level info
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=5
StartLimitIntervalSec=120
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}
KillMode=mixed
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" --quiet
systemctl start "${SERVICE_NAME}"
sleep 5

# Cek apakah backend running
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    print_ok "Backend service ${SERVICE_NAME} RUNNING"
else
    print_warn "Backend gagal start. Checking log..."
    journalctl -u "${SERVICE_NAME}" -n 20 --no-pager 2>/dev/null || true
fi

# ── Buat admin user ───────────────────────────────────────────────────────────
print_info "Membuat admin user pertama..."
cd "$APP_DIR/backend"
"$APP_DIR/backend/venv/bin/python3" - <<PYEOF
import asyncio, sys, os, uuid
from dotenv import load_dotenv
load_dotenv("${APP_DIR}/backend/.env")

from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def create_admin():
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URI") or "mongodb://localhost:27017"
    db_name   = os.environ.get("MONGO_DB_NAME", "nocsentinel")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    existing = await db.admin_users.find_one({"username": "admin"})
    if existing:
        print("  ⚠  Admin user 'admin' sudah ada, skip")
    else:
        await db.admin_users.insert_one({
            "id":        str(uuid.uuid4()),
            "username":  "admin",
            "password":  pwd_context.hash("${ADMIN_PASS}"),
            "role":      "administrator",
            "full_name": "Administrator",
            "email":     "admin@nocsentinel.local",
            "is_active": True,
        })
        print("  ✓  Admin user 'admin' berhasil dibuat")
    client.close()

asyncio.run(create_admin())
PYEOF

# ── Firewall ──────────────────────────────────────────────────────────────────
print_info "Konfigurasi firewall (ufw)..."
ufw --force enable > /dev/null 2>&1
ufw allow 22/tcp  > /dev/null 2>&1   # SSH
ufw allow 80/tcp  > /dev/null 2>&1   # HTTP
ufw allow 443/tcp > /dev/null 2>&1   # HTTPS
ufw allow ${SYSLOG_PORT}/udp > /dev/null 2>&1  # Syslog
print_ok "UFW firewall: SSH(22), HTTP(80), HTTPS(443), Syslog(${SYSLOG_PORT}/udp)"

# ── Symlink noc-update ────────────────────────────────────────────────────────
cp "$APP_DIR/update.sh" /usr/local/bin/noc-update 2>/dev/null || true
chmod +x /usr/local/bin/noc-update 2>/dev/null || true

# =============================================================================
#  SELESAI
# =============================================================================
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  ✅ INSTALASI SELESAI!                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""
echo -e "  ${BOLD}URL Aplikasi :${NC}  http://${SERVER_HOST}/"
echo -e "  ${BOLD}API Docs     :${NC}  http://${SERVER_HOST}/api/docs"
echo -e "  ${BOLD}Username     :${NC}  admin"
echo -e "  ${BOLD}Password     :${NC}  (yang Anda input tadi)"
echo ""
echo -e "  ${BOLD}Status Services:${NC}"

check_svc() {
    if systemctl is-active --quiet "$1"; then
        echo -e "    ${GREEN}✓${NC} $1: RUNNING"
    else
        echo -e "    ${RED}✗${NC} $1: FAILED (cek: journalctl -u $1 -n 30)"
    fi
}
check_svc "${SERVICE_NAME}"
check_svc "mongod"
check_svc "nginx"

echo ""
echo -e "  ${YELLOW}${BOLD}Langkah berikutnya:${NC}"
echo    "  1. Buka browser → http://${SERVER_HOST}/"
echo    "  2. Login dengan username: admin"
echo    "  3. Segera ganti password admin di Settings!"
echo    "  4. Tambah device MikroTik di menu Devices"
echo    "  5. Konfigurasi notifikasi WA/Telegram di menu Notifikasi"
echo    "  6. Untuk HTTPS: sudo certbot --nginx -d ${SERVER_HOST}"
echo ""
echo -e "  ${CYAN}Perintah berguna:${NC}"
echo    "  sudo journalctl -u ${SERVICE_NAME} -f       ← lihat log backend"
echo    "  sudo noc-update                              ← update aplikasi"
echo    "  sudo systemctl restart ${SERVICE_NAME}       ← restart backend"
echo ""
echo -e "  ${BOLD}Config file :${NC} ${APP_DIR}/backend/.env"
echo -e "  ${BOLD}Log backend :${NC} journalctl -u ${SERVICE_NAME}"
echo -e "  ${BOLD}Log nginx   :${NC} /var/log/nginx/nocsentinel_*.log"
echo ""
