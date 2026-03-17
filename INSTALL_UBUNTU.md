# NOC Sentinel v3 — Panduan Instalasi Ubuntu 20.04 / 22.04

## Persyaratan Server

| Komponen | Minimum | Rekomendasi |
|----------|---------|-------------|
| OS | Ubuntu 20.04 LTS | Ubuntu 22.04 LTS |
| RAM | 2 GB | 4 GB |
| Disk | 20 GB | 50 GB |
| CPU | 2 vCPU | 4 vCPU |
| Akses | Root / sudo | Root |
| Port | 22, 80, 443 | + 514/UDP (syslog) |

---

## ⚡ Install Otomatis (Rekomendasi — Fresh Ubuntu)

> Script ini menangani semua langkah secara otomatis: MongoDB, Python 3.11, Node.js 20, Nginx, systemd service, dan admin user.

```bash
# 1. Download script instalasi
curl -fsSL https://raw.githubusercontent.com/afani-arba/noc-sentinel-v3/main/install.sh -o install.sh

# 2. Jalankan sebagai root
sudo bash install.sh
```

Script akan menanyakan:
- **IP/Domain server** — IP publik atau domain (contoh: `192.168.1.10`)
- **Password MongoDB** — untuk user database
- **JWT Secret Key** — kosongkan untuk auto-generate (aman)
- **Password admin** — untuk login pertama ke aplikasi

> ⏱ **Waktu:** ~10-15 menit tergantung koneksi internet

---

## 🔄 Update Aplikasi (Server yang Sudah Terinstall)

Setelah install pertama, gunakan perintah ini untuk update:

```bash
# Opsi 1 — Menggunakan noc-update (shortcut otomatis dari installer)
sudo noc-update

# Opsi 2 — Manual via update.sh
cd /opt/noc-sentinel-v3
git pull origin main
sudo bash update.sh
```

Script update otomatis:
1. `git pull` — ambil kode terbaru dari GitHub
2. `pip install -r requirements.txt` — update Python packages
3. `npm install && npm run build` — rebuild frontend
4. Update systemd service
5. Restart backend

---

## 📋 Install Manual (Step by Step)

### Step 1 — Persiapan Sistem

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl wget git gnupg lsb-release build-essential \
    nginx openssl net-tools software-properties-common \
    certbot python3-certbot-nginx iputils-ping
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
# Import key MongoDB
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
pip install -r requirements.txt   # termasuk sse-starlette, influxdb-client
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

# Secret untuk JWT token (minimal 32 karakter)
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
> ```bash
> python3 -c "from urllib.parse import quote; print(quote('P@ssw0rd!', safe=''))"
> # Output: P%40ssw0rd%21
> ```

---

### Step 8 — Build Frontend

```bash
cd /opt/noc-sentinel-v3/frontend

# PENTING: gunakan --legacy-peer-deps agar sigma.js 3 kompatibel
npm install --legacy-peer-deps
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

    # Frontend React SPA
    location / {
        try_files $uri $uri/ /index.html;
    }

    # SSE (Server-Sent Events) — HARUS buffering off
    location /api/events/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }

    # Backend API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
        client_max_body_size 50M;
    }

    # Static assets caching
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
sudo systemctl enable nginx
```

---

### Step 10 — Systemd Service (Auto-start)

```bash
sudo nano /etc/systemd/system/nocsentinel.service
```

```ini
[Unit]
Description=NOC Sentinel v3 Backend (FastAPI)
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
User=root
Group=root
KillMode=mixed
TimeoutStopSec=10
WorkingDirectory=/opt/noc-sentinel-v3/backend
EnvironmentFile=/opt/noc-sentinel-v3/backend/.env
ExecStart=/opt/noc-sentinel-v3/backend/venv/bin/uvicorn server:app \
    --host 127.0.0.1 --port 8000 --workers 1 --loop asyncio
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5
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
import asyncio, os, uuid
from dotenv import load_dotenv
load_dotenv()

async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    from passlib.context import CryptContext
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

    mongo = os.environ.get('MONGO_URI') or 'mongodb://localhost:27017'
    db_name = os.environ.get('MONGO_DB_NAME', 'nocsentinel')

    client = AsyncIOMotorClient(mongo)
    db = client[db_name]

    if await db.admin_users.find_one({"username": "admin"}):
        print("Admin sudah ada")
        return

    await db.admin_users.insert_one({
        "id": str(uuid.uuid4()),
        "username": "admin",
        "password": pwd.hash("Admin123!"),   # ← ganti password ini!
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

## ✅ Verifikasi Instalasi

```bash
# 1. Cek semua service berjalan
systemctl status nocsentinel --no-pager
systemctl status mongod --no-pager
systemctl status nginx --no-pager

# 2. Cek API backend
curl -s http://localhost:8000/api/health
# atau test login
curl -s -X POST http://localhost/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"Admin123!"}' | python3 -m json.tool

# 3. Test SSE endpoint (Ctrl+C untuk stop)
curl -N http://localhost/api/events/devices?token=TEST
```

Buka browser: **`http://IP_SERVER/`**

Login:
- **Username:** `admin`
- **Password:** yang Anda buat saat instalasi

> 🔐 **SEGERA ganti password setelah login pertama!**

---

## 🔄 Update Aplikasi

```bash
# Cara paling mudah (setelah install pertama):
sudo noc-update

# Atau manual:
cd /opt/noc-sentinel-v3
git pull origin main
sudo bash update.sh
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

### Backend tidak berjalan (502 Bad Gateway)

```bash
# Lihat log error
journalctl -u nocsentinel -n 50 --no-pager

# Coba jalankan manual untuk lihat error langsung
cd /opt/noc-sentinel-v3/backend
source venv/bin/activate
python server.py
```

### MongoDB koneksi error

```bash
# Test koneksi
mongosh "mongodb://nocsentinel:PASSWORD@localhost/nocsentinel" \
    --eval "db.runCommand({ping:1})"

# Cek port
ss -tlnp | grep :27017
```

### Frontend blank / 404

```bash
# Pastikan build ada
ls /opt/noc-sentinel-v3/frontend/build/index.html

# Cek Nginx error
tail -20 /var/log/nginx/nocsentinel_error.log
nginx -t
```

### Dashboard LIVE badge tidak muncul (SSE tidak konek)

```bash
# Pastikan Nginx punya location /api/events/ dengan proxy_buffering off
grep -A5 "api/events" /etc/nginx/sites-available/nocsentinel

# Cek SSE poller di log backend
journalctl -u nocsentinel -n 20 | grep -i "sse\|poller"
```

### npm build error (sigma.js / peer deps)

```bash
cd /opt/noc-sentinel-v3/frontend
npm install --legacy-peer-deps  # ← PENTING untuk sigma@3
npm run build
```

### Port konflik di 8000

```bash
ss -tlnp | grep :8000
# Kill proses lama jika ada, lalu restart service
sudo systemctl restart nocsentinel
```

---

## 📁 Struktur Penting

```
/opt/noc-sentinel-v3/
├── backend/
│   ├── .env              ← Konfigurasi (JANGAN di-commit ke git!)
│   ├── venv/             ← Python virtual environment
│   ├── server.py         ← Entry point FastAPI
│   └── requirements.txt  ← Python dependencies
├── frontend/
│   ├── build/            ← Static files yang di-serve Nginx
│   └── package.json      ← Node.js dependencies
├── install.sh            ← Script instalasi fresh
├── update.sh             ← Script update
└── INSTALL_UBUNTU.md     ← Panduan ini
```

---

## 🔧 Service Management

```bash
# Status semua service
systemctl status nocsentinel mongod nginx

# Restart backend setelah update kode
sudo systemctl restart nocsentinel

# Lihat log real-time
journalctl -u nocsentinel -f

# Auto-start status (harus "enabled")
systemctl is-enabled nocsentinel mongod nginx
```

---

> **Repository:** https://github.com/afani-arba/noc-sentinel-v3  
> **Support:** Buat issue di GitHub jika ada masalah
