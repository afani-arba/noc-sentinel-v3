#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — WSL Auto-Installer (Ubuntu 22.04 LTS)
# Target : WSL Ubuntu 22.04 LTS
# Usage  : curl -fsSL https://raw.githubusercontent.com/afani-arba/noc-sentinel-v3/main/wsl_setup.sh | sudo bash
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

# ── Cek root ──────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && print_error "Jalankan sebagai root: sudo bash wsl_setup.sh"

# ── Cek Systemd di WSL ────────────────────────────────────────────────────────
if grep -qi "microsoft" /proc/version >/dev/null 2>&1; then
    if ! systemctl is-system-running >/dev/null 2>&1 && [ "$(pidof systemd)" == "" ]; then
        print_info "Mengkonfigurasi Systemd (Wajib untuk Ubuntu WSL)..."
        
        mkdir -p /etc
        if ! grep -q "systemd=true" /etc/wsl.conf 2>/dev/null; then
            echo -e "[boot]\nsystemd=true" >> /etc/wsl.conf
        fi
        
        print_ok "Konfigurasi systemd ditambahkan ke /etc/wsl.conf"
        echo ""
        echo -e "${YELLOW}${BOLD}⚠️  TINDAKAN DIPERLUKAN ⚠️${NC}"
        echo "Systemd harus aktif sebelum melanjutkan instalasi."
        echo "1. Buka Windows PowerShell (bukan WSL)"
        echo "2. Jalankan perintah:  wsl --shutdown"
        echo "3. Buka kembali WSL Ubuntu Anda"
        echo "4. Jalankan ulang script ini secara otomatis:"
        echo -e "${CYAN}   curl -fsSL https://raw.githubusercontent.com/afani-arba/noc-sentinel-v3/main/wsl_setup.sh | sudo bash${NC}"
        echo "=========================================================="
        exit 0
    fi
fi

# ── Konstanta ─────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/afani-arba/noc-sentinel-v3.git"
APP_DIR="/opt/noc-sentinel-v3"
MONGO_DB="nocsentinel"
MONGO_USER="nocsentinel"
SERVICE_NAME="nocsentinel"
NGINX_CONF="/etc/nginx/sites-available/nocsentinel"

# ── Default Auto-Config untuk WSL ─────────────────────────────────────────────
SERVER_HOST="localhost"
MONGO_PASS="nocsentinel123!"
ADMIN_PASS="Admin123!"
JWT_SECRET=$(openssl rand -hex 32)
SYSLOG_PORT=514

# URL-encode password untuk MongoDB URI
MONGO_PASS_ENCODED=$(python3 -c "
import urllib.parse, sys
print(urllib.parse.quote('${MONGO_PASS}', safe=''))
" 2>/dev/null || echo "${MONGO_PASS}")

echo -e "${BOLD}${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       NOC Sentinel v3 — Auto-Installer untuk WSL             ║"
echo "║          ARBA Network Monitoring System v3.0                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

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
    ufw 2>/dev/null || true

print_ok "System packages installed"

# =============================================================================
print_step "2/10 Install MongoDB 6.x"
# =============================================================================
if ! command -v mongod &>/dev/null; then
    print_info "Menginstall MongoDB 6.0..."
    curl -fsSL https://www.mongodb.org/static/pgp/server-6.0.asc | \
        gpg --dearmor -o /usr/share/keyrings/mongodb-server-6.0.gpg 2>/dev/null

    # Gunakan repository sesuai codename Ubuntu (jammy/focal)
    OS_CODE=$(lsb_release -cs 2>/dev/null || echo "jammy")
    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu ${OS_CODE}/mongodb-org/6.0 multiverse" \
        | tee /etc/apt/sources.list.d/mongodb-org-6.0.list > /dev/null

    apt-get update -qq
    apt-get --fix-broken install -y -qq
    apt-get install -y -qq mongodb-org
    print_ok "MongoDB 6.0 installed"
fi

systemctl enable mongod --quiet 2>/dev/null || true
systemctl start mongod 2>/dev/null || true
sleep 3

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

    if ! python3.11 -m pip --version &>/dev/null 2>&1; then
        curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 > /dev/null 2>&1
    fi
    print_ok "Python $(python3.11 --version) installed"
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
fi

# =============================================================================
print_step "5/10 Clone repository"
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
cp "$APP_DIR/backend/.env.example" "$ENV_FILE"
sed -i "s|mongodb://nocsentinel:GANTI_PASSWORD@localhost:27017/nocsentinel|mongodb://${MONGO_USER}:${MONGO_PASS_ENCODED}@localhost:27017/${MONGO_DB}|g" "$ENV_FILE"
sed -i "s|JWT_SECRET=GANTI_DENGAN_SECRET_KEY_ACAK_PANJANG|JWT_SECRET=${JWT_SECRET}|g" "$ENV_FILE"
sed -i "s|CORS_ORIGINS=http://localhost:3000|CORS_ORIGINS=http://${SERVER_HOST},http://${SERVER_HOST}:80,http://localhost:3000|g" "$ENV_FILE"
sed -i "s|SYSLOG_PORT=5140|SYSLOG_PORT=${SYSLOG_PORT}|g" "$ENV_FILE"
chmod 600 "$ENV_FILE"
print_ok ".env berhasil dibuat"

# =============================================================================
print_step "8/10 Build frontend (Vite + React)"
# =============================================================================
cd "$APP_DIR/frontend"
print_info "Menginstall npm packages (bisa butuh 3-5 menit)..."
npm install --legacy-peer-deps --prefer-offline 2>/dev/null || npm install --legacy-peer-deps
print_info "Building production bundle..."
npm run build
print_ok "Frontend berhasil di-build"

# =============================================================================
print_step "9/10 Konfigurasi Nginx"
# =============================================================================
rm -f /etc/nginx/sites-enabled/default
rm -f /etc/nginx/sites-enabled/noc-sentinel
rm -f /etc/nginx/sites-enabled/nocsentinel

cat > "$NGINX_CONF" <<NGINXEOF
server {
    listen 80;
    server_name ${SERVER_HOST} _;

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml application/json application/javascript
               application/xml+rss application/atom+xml image/svg+xml;

    root ${APP_DIR}/frontend/build;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

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
        client_max_body_size 50M;
    }

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|woff|woff2|ttf|svg|webp|map)\$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }
}
NGINXEOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/nocsentinel
nginx -t && systemctl restart nginx
systemctl enable nginx --quiet 2>/dev/null || true
print_ok "Nginx dikonfigurasi"

# =============================================================================
print_step "10/10 Setup Systemd Service & Admin User"
# =============================================================================
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<SVCEOF
[Unit]
Description=NOC Sentinel v3 Backend (FastAPI/Uvicorn)
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=${APP_DIR}/backend/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1 --loop asyncio
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" --quiet
systemctl start "${SERVICE_NAME}"
sleep 5

print_info "Membuat admin user..."
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
    if not existing:
        await db.admin_users.insert_one({
            "id":        str(uuid.uuid4()),
            "username":  "admin",
            "password":  pwd_context.hash("${ADMIN_PASS}"),
            "role":      "administrator",
            "full_name": "Administrator",
            "email":     "admin@nocsentinel.local",
            "is_active": True,
        })
    client.close()

asyncio.run(create_admin())
PYEOF

ufw --force enable > /dev/null 2>&1 || true
ufw allow 22/tcp  > /dev/null 2>&1 || true
ufw allow 80/tcp  > /dev/null 2>&1 || true

echo ""
echo -e "${GREEN}${BOLD}==========================================================${NC}"
echo -e "${GREEN}${BOLD}  ✅ INSTALASI NOC SENTINEL V3 DI WSL SELESAI!            ${NC}"
echo -e "${GREEN}${BOLD}==========================================================${NC}"
echo -e "  Akses Aplikasi : http://${SERVER_HOST}/"
echo -e "  Username       : admin"
echo -e "  Password       : ${ADMIN_PASS}"
echo ""
