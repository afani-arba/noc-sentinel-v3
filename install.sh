#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — Automated Install Script
# Target: Ubuntu 20.04 LTS (Focal Fossa) / Ubuntu 22.04 LTS
# Usage : sudo bash install.sh
# Repo  : https://github.com/afani-arba/noc-sentinel-v3
# =============================================================================

set -e

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

print_step()  { echo -e "\n${BLUE}${BOLD}▶ $1${NC}"; }
print_ok()    { echo -e "${GREEN}✓ $1${NC}"; }
print_warn()  { echo -e "${YELLOW}⚠ $1${NC}"; }
print_error() { echo -e "${RED}✗ ERROR: $1${NC}"; exit 1; }

# ── Config ───────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/afani-arba/noc-sentinel-v3.git"
APP_DIR="/opt/noc-sentinel-v3"
MONGO_DB="nocsentinel"
MONGO_USER="nocsentinel"
SERVICE_NAME="nocsentinel"
NGINX_CONF="/etc/nginx/sites-available/nocsentinel"

# ── Check root ───────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && print_error "Jalankan sebagai root: sudo bash install.sh"

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║      NOC Sentinel v3 — Installer Ubuntu 20.04        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Input konfigurasi ────────────────────────────────────────────────────────
print_step "Konfigurasi Instalasi"
read -rp  "IP/Domain server (contoh: 192.168.1.10 atau monitoring.example.com): " SERVER_HOST
read -rsp "Password MongoDB untuk user '$MONGO_USER': " MONGO_PASS; echo
read -rsp "JWT Secret Key (kosong = auto-generate 64 karakter acak): " SECRET_KEY; echo
read -rsp "Password admin pertama NOC Sentinel (contoh: Admin123!): " ADMIN_PASS; echo

[[ -z "$MONGO_PASS" ]] && print_error "Password MongoDB tidak boleh kosong"
[[ -z "$ADMIN_PASS" ]] && print_error "Password admin tidak boleh kosong"

if [[ -z "$SECRET_KEY" ]]; then
    SECRET_KEY=$(openssl rand -hex 32)
    print_ok "JWT Secret auto-generated"
fi

# URL-encode karakter khusus dalam password MongoDB
MONGO_PASS_ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${MONGO_PASS}', safe=''))" 2>/dev/null || \
    python3 -c "from urllib.parse import quote; print(quote('${MONGO_PASS}', safe=''))")

# =============================================================================
print_step "1/10 Update sistem & install dependency"
# =============================================================================
apt update -qq
apt install -y -qq \
    curl wget git gnupg lsb-release \
    build-essential software-properties-common \
    nginx openssl net-tools iputils-ping \
    libssl-dev libffi-dev python3-dev pkg-config \
    certbot python3-certbot-nginx
print_ok "System packages installed"

# =============================================================================
print_step "2/10 Clone repository dari GitHub"
# =============================================================================
if [[ -d "$APP_DIR/.git" ]]; then
    print_warn "Direktori sudah ada — git pull..."
    cd "$APP_DIR"
    git remote set-url origin "$REPO_URL" 2>/dev/null || true
    git pull origin main
else
    print_ok "Cloning $REPO_URL → $APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
fi
print_ok "Source code siap di $APP_DIR"

# =============================================================================
print_step "3/10 Install MongoDB 6.x"
# =============================================================================
if ! command -v mongod &>/dev/null; then
    # Import MongoDB GPG key
    curl -fsSL https://www.mongodb.org/static/pgp/server-6.0.asc | \
        gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor 2>/dev/null

    # Add repo (focal = Ubuntu 20.04, jammy = Ubuntu 22.04)
    UBUNTU_CODENAME=$(lsb_release -cs)
    if [[ "$UBUNTU_CODENAME" == "focal" ]]; then
        MONGO_CODENAME="focal"
    else
        MONGO_CODENAME="jammy"
    fi

    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu ${MONGO_CODENAME}/mongodb-org/6.0 multiverse" | \
        tee /etc/apt/sources.list.d/mongodb-org-6.0.list > /dev/null

    apt update -qq
    apt install -y -qq mongodb-org
    print_ok "MongoDB 6.x installed"
else
    print_warn "MongoDB sudah ada: $(mongod --version | head -1)"
fi

systemctl enable mongod --quiet
systemctl start mongod
sleep 3

# Buat user MongoDB
MONGO_CHECK=$(mongosh --quiet --eval \
    "db.getSiblingDB('$MONGO_DB').getUsers().users.filter(u => u.user === '$MONGO_USER').length" \
    2>/dev/null || echo "0")

if [[ "$MONGO_CHECK" == "0" ]]; then
    mongosh --quiet <<EOF
use $MONGO_DB
db.createUser({
  user: "$MONGO_USER",
  pwd: "$MONGO_PASS",
  roles: [{ role: "readWrite", db: "$MONGO_DB" }]
})
EOF
    print_ok "MongoDB user '$MONGO_USER' dibuat"
else
    print_warn "MongoDB user '$MONGO_USER' sudah ada, skip"
fi

# Enable auth
if ! grep -q "authorization: enabled" /etc/mongod.conf 2>/dev/null; then
    cat >> /etc/mongod.conf <<'MONGOEOF'

security:
  authorization: enabled
MONGOEOF
    systemctl restart mongod
    sleep 2
    print_ok "MongoDB authentication enabled"
fi

# =============================================================================
print_step "4/10 Install Python 3.11"
# =============================================================================
if ! command -v python3.11 &>/dev/null; then
    add-apt-repository ppa:deadsnakes/ppa -y > /dev/null 2>&1
    apt update -qq
    apt install -y -qq python3.11 python3.11-venv python3.11-dev
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 > /dev/null 2>&1
    print_ok "Python 3.11 installed"
else
    print_warn "Python 3.11 sudah ada: $(python3.11 --version)"
fi

# =============================================================================
print_step "5/10 Install Node.js 20 LTS"
# =============================================================================
NODE_MAJOR=$(node --version 2>/dev/null | cut -dv -f2 | cut -d. -f1 || echo "0")
if [[ "$NODE_MAJOR" -lt 18 ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
    apt install -y -qq nodejs
    print_ok "Node.js $(node --version) installed"
else
    print_warn "Node.js $(node --version) sudah ada"
fi

# =============================================================================
print_step "6/10 Setup Python venv & install dependencies"
# =============================================================================
cd "$APP_DIR/backend"

[[ ! -d "venv" ]] && python3.11 -m venv venv

source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
deactivate
print_ok "Python packages installed"

# =============================================================================
print_step "7/10 Setup file .env backend"
# =============================================================================
ENV_FILE="$APP_DIR/backend/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$APP_DIR/backend/.env.example" "$ENV_FILE"
    sed -i "s|mongodb://nocsentinel:GANTI_PASSWORD@localhost|mongodb://${MONGO_USER}:${MONGO_PASS_ENCODED}@localhost|g" "$ENV_FILE"
    sed -i "s|GANTI_DENGAN_SECRET_KEY_ACAK_PANJANG|${SECRET_KEY}|g" "$ENV_FILE"
    sed -i "s|CORS_ORIGINS=http://localhost:3000|CORS_ORIGINS=http://${SERVER_HOST},http://${SERVER_HOST}:80|g" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    print_ok ".env dibuat"
else
    print_warn ".env sudah ada, tidak ditimpa"
fi

# =============================================================================
print_step "8/10 Build frontend (Vite)"
# =============================================================================
cd "$APP_DIR/frontend"

print_ok "Installing npm packages..."
npm install

print_ok "Building production bundle..."
npm run build

[[ -f "build/index.html" ]] || print_error "Build gagal — build/index.html tidak ditemukan"
print_ok "Frontend berhasil di-build → build/"

# =============================================================================
print_step "9/10 Konfigurasi Nginx"
# =============================================================================

# Hapus config lama yang bentrok
rm -f /etc/nginx/sites-enabled/default
rm -f /etc/nginx/sites-enabled/noc-sentinel
rm -f /etc/nginx/sites-enabled/noc-sentinel-v3

cat > "$NGINX_CONF" <<NGINXEOF
server {
    listen 80;
    server_name ${SERVER_HOST} _;

    gzip on;
    gzip_types text/plain application/json application/javascript text/css application/xml image/svg+xml;
    gzip_min_length 1000;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    root ${APP_DIR}/frontend/build;
    index index.html;

    # Frontend – React SPA routing
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Backend API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        client_max_body_size 50M;
    }

    # Static assets caching
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|woff|woff2|ttf|svg|webp)\$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    access_log /var/log/nginx/nocsentinel_access.log;
    error_log  /var/log/nginx/nocsentinel_error.log;
}
NGINXEOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/nocsentinel
nginx -t
systemctl restart nginx
systemctl enable nginx --quiet
print_ok "Nginx configured"

# =============================================================================
print_step "10/10 Systemd service & admin user"
# =============================================================================

# Fix permissions
chown -R www-data:www-data "$APP_DIR/backend"
chmod -R 755 "$APP_DIR/frontend/build"
chmod 600 "$APP_DIR/backend/.env"
chown www-data:www-data "$APP_DIR/backend/.env"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<SVCEOF
[Unit]
Description=NOC Sentinel v3 Backend (FastAPI)
After=network.target mongod.service
Requires=mongod.service

[Service]
Type=simple
User=www-data
Group=www-data
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
sleep 4

# Buat admin user langsung
print_ok "Membuat admin user..."

# Load .env untuk mendapatkan MONGO_URI
source "$APP_DIR/backend/.env" 2>/dev/null || true

cd "$APP_DIR/backend"
"$APP_DIR/backend/venv/bin/python3" - <<PYEOF
import asyncio, sys, os

# Load .env dengan path eksplisit (find_dotenv() gagal di heredoc stdin)
from dotenv import load_dotenv
load_dotenv('$APP_DIR/backend/.env')

sys.path.insert(0, '$APP_DIR/backend')


async def create_admin():
    from core.db import init_db
    from core.auth import hash_password
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_url = os.environ.get('MONGO_URI') or os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    db_name   = os.environ.get('MONGO_DB_NAME') or os.environ.get('DB_NAME', 'nocsentinel')

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    existing = await db.users.find_one({"username": "admin"})
    if existing:
        print("⚠  Admin user sudah ada, skip")
        client.close()
        return

    await db.users.insert_one({
        "username": "admin",
        "password": hash_password("${ADMIN_PASS}"),
        "role": "administrator",
        "full_name": "Administrator",
        "email": "admin@nocsentinel.local",
        "is_active": True,
    })
    print("✓  Admin user 'admin' berhasil dibuat")
    client.close()

asyncio.run(create_admin())
PYEOF

# Firewall
ufw --force enable > /dev/null 2>&1
ufw allow 22/tcp  > /dev/null
ufw allow 80/tcp  > /dev/null
ufw allow 443/tcp > /dev/null
ufw allow 514/udp > /dev/null
print_ok "UFW firewall configured"

# =============================================================================
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════╗"
echo    "║          ✅ INSTALASI SELESAI!                        ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}URL Akses :${NC}  http://${SERVER_HOST}/"
echo -e "  ${BOLD}API Docs  :${NC}  http://${SERVER_HOST}/api/docs"
echo -e "  ${BOLD}Username  :${NC}  admin"
echo -e "  ${BOLD}Password  :${NC}  (yang Anda masukkan tadi)"
echo ""

if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo -e "  ${GREEN}${BOLD}✓ Backend ${SERVICE_NAME}: RUNNING${NC}"
else
    echo -e "  ${RED}✗ Backend GAGAL START — cek log:${NC}"
    echo    "    journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
fi

echo ""
echo -e "  ${YELLOW}Langkah berikutnya:${NC}"
echo    "  1. Login dan SEGERA GANTI PASSWORD admin!"
echo    "  2. Tambah device MikroTik: Settings → Devices"
echo    "  3. Untuk HTTPS: certbot --nginx -d domain.anda.com"
echo ""
