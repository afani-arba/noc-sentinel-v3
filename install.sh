#!/bin/bash
# =============================================================================
# NOC Sentinel v3 — Automated Install Script for Ubuntu Server 20.04
# Usage: sudo bash install.sh
#
# Source: https://github.com/afani-arba/noc-sentinel
# =============================================================================

set -e  # Exit on any error

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

print_step()  { echo -e "\n${BLUE}${BOLD}▶ $1${NC}"; }
print_ok()    { echo -e "${GREEN}✓ $1${NC}"; }
print_warn()  { echo -e "${YELLOW}⚠ $1${NC}"; }
print_error() { echo -e "${RED}✗ ERROR: $1${NC}"; exit 1; }

# ── Config ───────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/afani-arba/noc-sentinel.git"
APP_DIR="/opt/noc-sentinel-v3"
MONGO_DB="nocsentinel"
MONGO_USER="nocsentinel"
SERVICE_NAME="nocsentinel"
NGINX_CONF="/etc/nginx/sites-available/nocsentinel"

# ── Check root ───────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
   print_error "Jalankan sebagai root: sudo bash install.sh"
fi

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║      NOC Sentinel v3 — Installer Ubuntu 20.04        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Input konfigurasi ────────────────────────────────────────────────────────
print_step "Konfigurasi Instalasi"
read -rp  "IP/Domain server ini (contoh: 192.168.1.10): " SERVER_HOST
read -rsp "Password MongoDB user '$MONGO_USER': " MONGO_PASS; echo
read -rsp "JWT Secret Key (kosong = auto-generate): " SECRET_KEY; echo

if [[ -z "$SECRET_KEY" ]]; then
    SECRET_KEY=$(openssl rand -hex 32)
    print_ok "Secret key auto-generated"
fi

# ─────────────────────────────────────────────────────────────────────────────
print_step "1/10 Update sistem & install dependency"
# ─────────────────────────────────────────────────────────────────────────────
apt update -qq
apt upgrade -y -qq
apt install -y -qq \
    curl wget git unzip build-essential \
    software-properties-common \
    nginx snmp net-tools iputils-ping \
    libssl-dev libffi-dev python3-dev pkg-config \
    certbot python3-certbot-nginx
print_ok "System packages installed"

# ─────────────────────────────────────────────────────────────────────────────
print_step "2/10 Clone / Update source dari GitHub"
# ─────────────────────────────────────────────────────────────────────────────
if [[ -d "$APP_DIR/.git" ]]; then
    print_warn "Direktori $APP_DIR sudah ada — menjalankan git pull..."
    cd "$APP_DIR"
    git pull origin main || git pull origin master
else
    print_ok "Cloning dari $REPO_URL..."
    git clone "$REPO_URL" "$APP_DIR"
fi
print_ok "Source code siap di $APP_DIR"

# ─────────────────────────────────────────────────────────────────────────────
print_step "3/10 Install MongoDB 6.x"
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v mongod &>/dev/null; then
    curl -fsSL https://www.mongodb.org/static/pgp/server-6.0.asc | \
        gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor 2>/dev/null

    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] \
        https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/6.0 multiverse" | \
        tee /etc/apt/sources.list.d/mongodb-org-6.0.list > /dev/null

    apt update -qq
    apt install -y -qq mongodb-org
    print_ok "MongoDB 6.x installed"
else
    print_warn "MongoDB sudah ada: $(mongod --version | head -1)"
fi

systemctl enable mongod --quiet
systemctl start mongod
sleep 2

# Buat MongoDB user (hanya jika belum ada)
MONGO_CHECK=$(mongosh --quiet --eval "db.getUsers().users.filter(u => u.user === '$MONGO_USER').length" "$MONGO_DB" 2>/dev/null || echo "0")
if [[ "$MONGO_CHECK" == "0" ]]; then
    mongosh --quiet <<EOF
use $MONGO_DB
db.createUser({
  user: "$MONGO_USER",
  pwd: "$MONGO_PASS",
  roles: [{ role: "readWrite", db: "$MONGO_DB" }]
})
exit
EOF
    print_ok "MongoDB user '$MONGO_USER' created"
else
    print_warn "MongoDB user '$MONGO_USER' sudah ada, skip"
fi

# Enable MongoDB auth
MONGOD_CONF="/etc/mongod.conf"
if ! grep -q "authorization: enabled" "$MONGOD_CONF"; then
    printf '\nsecurity:\n  authorization: enabled\n' >> "$MONGOD_CONF"
    systemctl restart mongod
    sleep 2
    print_ok "MongoDB authentication enabled"
fi

# ─────────────────────────────────────────────────────────────────────────────
print_step "4/10 Install Python 3.11"
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v python3.11 &>/dev/null; then
    add-apt-repository ppa:deadsnakes/ppa -y > /dev/null 2>&1
    apt update -qq
    apt install -y -qq python3.11 python3.11-venv python3.11-dev python3.11-distutils
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 > /dev/null 2>&1
    print_ok "Python 3.11 installed"
else
    print_warn "Python 3.11 sudah ada: $(python3.11 --version)"
fi

# ─────────────────────────────────────────────────────────────────────────────
print_step "5/10 Install Node.js 18 LTS"
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null || [[ $(node --version | cut -d'v' -f2 | cut -d'.' -f1) -lt 16 ]]; then
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - > /dev/null 2>&1
    apt install -y -qq nodejs
    print_ok "Node.js $(node --version) installed"
else
    print_warn "Node.js $(node --version) sudah ada, skip"
fi

# ─────────────────────────────────────────────────────────────────────────────
print_step "6/10 Setup Python virtual environment"
# ─────────────────────────────────────────────────────────────────────────────
cd "$APP_DIR/backend"

if [[ ! -d "venv" ]]; then
    python3.11 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
deactivate
print_ok "Python packages installed in venv"

# ─────────────────────────────────────────────────────────────────────────────
print_step "7/10 Setup file .env"
# ─────────────────────────────────────────────────────────────────────────────
ENV_FILE="$APP_DIR/backend/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$APP_DIR/backend/.env.example" "$ENV_FILE"
    # Replace placeholder values
    sed -i "s|mongodb://nocsentinel:GANTI_PASSWORD@localhost|mongodb://${MONGO_USER}:${MONGO_PASS}@localhost|g" "$ENV_FILE"
    sed -i "s|GANTI_DENGAN_SECRET_KEY_ACAK_PANJANG|${SECRET_KEY}|g" "$ENV_FILE"
    sed -i "s|CORS_ORIGINS=http://localhost:3000|CORS_ORIGINS=http://${SERVER_HOST}|g" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    print_ok ".env dibuat dari .env.example"
else
    print_warn ".env sudah ada, tidak ditimpa. Cek manual: nano $ENV_FILE"
fi

# ─────────────────────────────────────────────────────────────────────────────
print_step "8/10 Build frontend (Vite)"
# ─────────────────────────────────────────────────────────────────────────────
cd "$APP_DIR/frontend"
npm install --legacy-peer-deps
npm run build
print_ok "Frontend built → $APP_DIR/frontend/build/"


# ─────────────────────────────────────────────────────────────────────────────
print_step "9/10 Konfigurasi Nginx"
# ─────────────────────────────────────────────────────────────────────────────
cat > "$NGINX_CONF" <<NGINXEOF
server {
    listen 80;
    server_name ${SERVER_HOST};

    gzip on;
    gzip_types text/plain application/json application/javascript text/css;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    root ${APP_DIR}/frontend/build;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

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

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|woff|woff2|ttf|svg)\$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    access_log /var/log/nginx/nocsentinel_access.log;
    error_log  /var/log/nginx/nocsentinel_error.log;
}
NGINXEOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/nocsentinel
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
systemctl enable nginx --quiet
print_ok "Nginx configured"

# ─────────────────────────────────────────────────────────────────────────────
print_step "10/10 Systemd service"
# ─────────────────────────────────────────────────────────────────────────────

# Fix permissions
chown -R www-data:www-data "$APP_DIR/backend"
chmod -R 755 "$APP_DIR/frontend/build"

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
Environment="PATH=${APP_DIR}/backend/venv/bin"
ExecStart=${APP_DIR}/backend/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1 --loop asyncio
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" --quiet
systemctl start "${SERVICE_NAME}"
sleep 3

# ── Firewall ─────────────────────────────────────────────────────────────────
ufw --force enable > /dev/null 2>&1
ufw allow 22/tcp > /dev/null
ufw allow 80/tcp > /dev/null
ufw allow 443/tcp > /dev/null
ufw allow 514/udp > /dev/null
print_ok "UFW firewall configured"

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════╗"
echo    "║          ✅ INSTALASI SELESAI!                        ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Repository:${NC} $REPO_URL"
echo -e "  ${BOLD}URL Akses:${NC}   http://${SERVER_HOST}/"
echo -e "  ${BOLD}API Docs:${NC}    http://${SERVER_HOST}/api/docs"
echo ""
# Check backend status
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo -e "  ${GREEN}${BOLD}✓ Backend nocsentinel: RUNNING${NC}"
else
    echo -e "  ${RED}✗ Backend GAGAL START — jalankan:${NC}"
    echo -e "    journalctl -u ${SERVICE_NAME} -n 50"
fi
echo ""
echo -e "  ${YELLOW}${BOLD}Langkah Selanjutnya:${NC}"
echo    "  Buat admin user:"
echo    "    sudo bash ${APP_DIR}/scripts/create-admin.sh"
echo ""
echo -e "  ${YELLOW}Jika perlu HTTPS (domain name):${NC}"
echo    "    sudo certbot --nginx -d namadomainanda.com"
echo ""
