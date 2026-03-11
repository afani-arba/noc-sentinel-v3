# NOC Sentinel v3 — Tutorial Instalasi Ubuntu 20.04/22.04

## Persyaratan Server

| Komponen | Minimum | Rekomendasi |
|----------|---------|-------------|
| OS | Ubuntu 20.04 LTS | Ubuntu 22.04 LTS |
| RAM | 2 GB | 4 GB |
| Disk | 20 GB | 50 GB |
| CPU | 2 vCPU | 4 vCPU |
| Akses | Root / sudo | Root |
| Port Terbuka | 22, 80, 443 | + 514/UDP (syslog) |

---

## ⚡ Cara Install Otomatis (Rekomendasi)

```bash
# 1. Download script instalasi
curl -fsSL https://raw.githubusercontent.com/afani-arba/noc-sentinel-v3/main/install.sh -o install.sh

# 2. Jalankan sebagai root
sudo bash install.sh
```

Script akan menanyakan:
- **IP/Domain server** — IP publik atau domain (contoh: `192.168.1.10`)
- **Password MongoDB** — untuk database user
- **JWT Secret Key** — kosongkan untuk auto-generate
- **Password admin** — untuk login pertama ke aplikasi

> ⏱ **Waktu:** ~5-10 menit tergantung koneksi internet

---

## 📋 Cara Install Manual (Step by Step)

### Step 1 — Persiapan Sistem

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl wget git gnupg lsb-release build-essential \
    nginx openssl net-tools software-properties-common \
    certbot python3-certbot-nginx
```

---

### Step 2 — Clone Repository

```bash
sudo git clone https://github.com/afani-arba/noc-sentinel-v3.git /opt/noc-sentinel-v3
cd /opt/noc-sentinel-v3
```

---

### Step 3 — Install MongoDB 6.x

```bash
# Import key
curl -fsSL https://www.mongodb.org/static/pgp/server-6.0.asc | \
    sudo gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor

# Ubuntu 20.04 (focal):
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] \
    https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/6.0 multiverse" | \
    sudo tee /etc/apt/sources.list.d/mongodb-org-6.0.list

# Ubuntu 22.04 (jammy) — ganti focal → jammy di baris di atas

sudo apt update && sudo apt install -y mongodb-org
sudo systemctl enable mongod && sudo systemctl start mongod
sleep 3

# Buat database user
mongosh <<'EOF'
use nocsentinel
db.createUser({
  user: "nocsentinel",
  pwd: "PASSWORD_MONGO_ANDA",   // ← ganti ini
  roles: [{ role: "readWrite", db: "nocsentinel" }]
})
EOF

# Enable authentication
echo -e "\nsecurity:\n  authorization: enabled" | sudo tee -a /etc/mongod.conf
sudo systemctl restart mongod
```

---

### Step 4 — Install Python 3.11

```bash
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3.11
```

---

### Step 5 — Install Node.js 20 LTS

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs
node --version   # harus v20.x.x
```

---

### Step 6 — Setup Backend Python

```bash
cd /opt/noc-sentinel-v3/backend
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
```

---

### Step 7 — Konfigurasi File .env

```bash
cd /opt/noc-sentinel-v3/backend
cp .env.example .env
nano .env
```

Isi minimal yang harus diubah:

```env
# MongoDB — URL-encode karakter khusus di password (@ → %40, ! → %21)
MONGO_URI=mongodb://nocsentinel:PASSWORD_ANDA@localhost:27017/nocsentinel

# Secret untuk JWT token
SECRET_KEY=isi-dengan-string-acak-panjang-minimal-32-karakter

# IP/domain server untuk CORS
CORS_ORIGINS=http://192.168.1.10,http://192.168.1.10:80

# Database
MONGO_DB_NAME=nocsentinel
```

```bash
chmod 600 .env
```

> ⚠️ **Password dengan karakter khusus** harus di-URL-encode:
> `!` → `%21`, `@` → `%40`, `#` → `%23`, `$` → `%24`
>
> Gunakan Python untuk encode:
> ```bash
> python3 -c "from urllib.parse import quote; print(quote('P@ssw0rd!', safe=''))"
> # Output: P%40ssw0rd%21
> ```

---

### Step 8 — Build Frontend (Vite)

```bash
cd /opt/noc-sentinel-v3/frontend
npm install
npm run build

# Verifikasi
ls build/index.html && echo "✅ Build sukses!"
```

---

### Step 9 — Konfigurasi Nginx

```bash
sudo nano /etc/nginx/sites-available/nocsentinel
```

Isi dengan:
```nginx
server {
    listen 80;
    server_name IP_ATAU_DOMAIN_ANDA;

    root /opt/noc-sentinel-v3/frontend/build;
    index index.html;

    gzip on;
    gzip_types text/plain application/json application/javascript text/css;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
        client_max_body_size 50M;
    }

    location ~* \.(js|css|png|jpg|ico|woff|woff2|svg)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    access_log /var/log/nginx/nocsentinel_access.log;
    error_log  /var/log/nginx/nocsentinel_error.log;
}
```

```bash
sudo ln -sf /etc/nginx/sites-available/nocsentinel /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

---

### Step 10 — Systemd Service Backend

```bash
# Fix permissions
sudo chown -R www-data:www-data /opt/noc-sentinel-v3/backend
sudo chmod 600 /opt/noc-sentinel-v3/backend/.env

# Buat service
sudo nano /etc/systemd/system/nocsentinel.service
```

```ini
[Unit]
Description=NOC Sentinel v3 Backend (FastAPI)
After=network.target mongod.service
Requires=mongod.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/noc-sentinel-v3/backend
EnvironmentFile=/opt/noc-sentinel-v3/backend/.env
ExecStart=/opt/noc-sentinel-v3/backend/venv/bin/uvicorn server:app \
    --host 127.0.0.1 --port 8000 --workers 1 --loop asyncio
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable nocsentinel
sudo systemctl start nocsentinel
sleep 3
sudo systemctl status nocsentinel  # harus Active: active (running)
```

---

### Step 11 — Buat Admin User

```bash
cd /opt/noc-sentinel-v3/backend
source venv/bin/activate

python3 - << 'EOF'
import asyncio, os
from dotenv import load_dotenv
load_dotenv()

async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    from core.auth import hash_password

    mongo = os.environ.get('MONGO_URI') or os.environ.get('MONGO_URL')
    db_name = os.environ.get('MONGO_DB_NAME') or os.environ.get('DB_NAME', 'nocsentinel')

    client = AsyncIOMotorClient(mongo)
    db = client[db_name]

    if await db.users.find_one({"username": "admin"}):
        print("Admin sudah ada")
        return

    await db.users.insert_one({
        "username": "admin",
        "password": hash_password("Admin123!"),   # ← ganti password ini!
        "role": "administrator",
        "full_name": "Administrator",
        "email": "admin@local",
        "is_active": True,
    })
    print("✓ Admin user 'admin' berhasil dibuat")
    client.close()

asyncio.run(main())
EOF

deactivate
```

---

### Step 12 — Firewall (UFW)

```bash
sudo ufw enable
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 514/udp   # Syslog (opsional)
sudo ufw status
```

---

## ✅ Verifikasi Instalasi

```bash
# 1. Cek backend API
curl -s http://localhost/api/health || \
curl -s -X POST http://localhost/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"Admin123!"}' | python3 -m json.tool

# 2. Cek service status
systemctl status nocsentinel --no-pager
systemctl status mongod --no-pager
systemctl status nginx --no-pager
```

Buka browser: **`http://IP_SERVER/`**

Login:
- **Username:** `admin`
- **Password:** `Admin123!` (atau yang Anda buat)

> 🔐 **SEGERA ganti password setelah login pertama!**

---

## 🔄 Update Aplikasi

```bash
cd /opt/noc-sentinel-v3

# Pull update terbaru
git pull origin main

# Update backend
source backend/venv/bin/activate
pip install -r backend/requirements.txt -q
deactivate

# Rebuild frontend
cd frontend
npm install
npm run build
cd ..

# Restart service
sudo systemctl restart nocsentinel
echo "✅ Update selesai"
```

---

## 🌐 HTTPS dengan Let's Encrypt

```bash
# Pastikan domain sudah mengarah ke IP server
sudo certbot --nginx -d namadomainanda.com
sudo systemctl reload nginx
```

---

## 🛠️ Troubleshooting

### Backend tidak berjalan
```bash
journalctl -u nocsentinel -n 50 --no-pager
```

**MONGO_URI error:**
```bash
# Test koneksi MongoDB
mongosh "mongodb://nocsentinel:PASSWORD@localhost/nocsentinel" --eval "db.runCommand({ping:1})"
```

**Port konflik:**
```bash
ss -tlnp | grep :8000
```

### Frontend tampil blank / 404
```bash
# Pastikan build ada
ls /opt/noc-sentinel-v3/frontend/build/index.html

# Cek Nginx error
tail -20 /var/log/nginx/nocsentinel_error.log
nginx -t
```

### Login 500 Internal Server Error
```bash
# Cek CORS di .env
grep CORS /opt/noc-sentinel-v3/backend/.env

# Test backend langsung
curl -s http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin123!"}'
```

### Syslog tidak terima log
```bash
# Cek port syslog di .env
grep SYSLOG /opt/noc-sentinel-v3/backend/.env
# Default: SYSLOG_PORT=5141
ss -ulnp | grep 5141
```

---

> **Repository:** https://github.com/afani-arba/noc-sentinel-v3
