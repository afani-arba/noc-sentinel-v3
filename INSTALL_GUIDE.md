# NOC Sentinel v3 — Panduan Instalasi Lengkap
## Fresh Install di Ubuntu 20.04 LTS (Focal Fossa)

> **Target Server:** Ubuntu 20.04 LTS (Focal Fossa) — 64-bit  
> **Minimum Spec:** 2 vCPU, 2GB RAM, 20GB SSD  
> **Memantau:** Hingga 100 device MikroTik secara real-time

---

## ⚡ Instalasi Cepat (1 Command)

```bash
# Jalankan sebagai root (sudo)
sudo bash -c "curl -fsSL https://raw.githubusercontent.com/afani-arba/noc-sentinel-v3/main/install.sh | bash"
```

**Atau clone dulu, lalu install:**
```bash
git clone https://github.com/afani-arba/noc-sentinel-v3.git
cd noc-sentinel-v3
sudo bash install.sh
```

---

## 📋 Prasyarat

### Server Ubuntu 20.04 LTS
```bash
# Cek versi OS
lsb_release -a
# Harus: Ubuntu 20.04.x LTS

# Update sistem dulu
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git
```

### Akses Root / Sudo
```bash
# Pastikan user memiliki sudo
sudo -v
```

### Port yang Harus Terbuka
| Port | Protocol | Kegunaan |
|------|----------|----------|
| 22   | TCP      | SSH admin server |
| 80   | TCP      | HTTP akses aplikasi |
| 443  | TCP      | HTTPS (opsional, setelah setup SSL) |
| 514  | UDP      | Syslog dari MikroTik (dapat diubah) |

---

## 🚀 Langkah Instalasi Lengkap

### Step 1 — Persiapan Server

```bash
# Login ke server via SSH sebagai root atau user dengan sudo
ssh root@IP_SERVER_ANDA
# atau
ssh username@IP_SERVER_ANDA

# Pastikan tanggal/waktu server benar (penting untuk JWT)
timedatectl set-timezone Asia/Jakarta
timedatectl

# Update sistem
apt update && apt upgrade -y
```

### Step 2 — Download & Jalankan Installer

```bash
# Clone repository
git clone https://github.com/afani-arba/noc-sentinel-v3.git
cd noc-sentinel-v3

# Jalankan installer
sudo bash install.sh
```

### Step 3 — Isi Konfigurasi (Installer akan tanya)

```
IP atau domain server   : 192.168.1.10   ← IP server Anda
Password MongoDB        : MongoPass123!  ← password database (ingat ini!)
Password admin NOC      : Admin@123!     ← min 8 karakter
JWT Secret              : (Enter = auto-generate, DISARANKAN)
Port Syslog UDP         : 514            ← atau tekan Enter default
```

> ⚠️ **PENTING:** Catat password yang dimasukkan! Khususnya MongoDB password.

### Step 4 — Tunggu Proses (estimasi 10-15 menit)

Proses yang terjadi secara otomatis:
1. Install MongoDB 6.0
2. Install Python 3.11
3. Install Node.js 20 LTS
4. Clone/update source code
5. Setup Python virtual environment + install packages
6. Build frontend React (Vite)
7. Konfigurasi Nginx
8. Setup systemd service
9. Buat user admin pertama
10. Konfigurasi firewall (UFW)

### Step 5 — Verifikasi Instalasi

```bash
# Cek semua service running
systemctl status nocsentinel
systemctl status mongod
systemctl status nginx

# Atau cek sekaligus
systemctl is-active nocsentinel mongod nginx

# Cek log backend
journalctl -u nocsentinel -n 50 --no-pager
```

### Step 6 — Akses Aplikasi

Buka browser:
```
http://IP_SERVER_ANDA/
```

Login dengan:
- **Username:** `admin`
- **Password:** *(yang Anda input saat instalasi)*

---

## ⚙️ Konfigurasi Pasca-Instalasi

### 1. Ganti Password Admin

Setelah login pertama, segera ganti password:
→ **Settings → Admin → Edit User Admin**

### 2. Tambah Device MikroTik

→ **Menu Devices → Add Device**

Informasi yang dibutuhkan:
- Nama device
- IP Address MikroTik
- Username API (admin)
- Password API
- Mode: REST API (ROS 7.x) atau API Socket (ROS 6.x)

> **Untuk ROS 7.x:** Aktifkan www service di MikroTik:
> ```
> /ip service set www disabled=no port=80
> /ip service set www-ssl disabled=no port=443
> ```

> **Untuk ROS 6.x:** Aktifkan API service:
> ```
> /ip service set api disabled=no port=8728
> ```

### 3. Konfigurasi Notifikasi

→ **Menu Notifikasi → Settings**

- **WhatsApp (Fonnte):** Masukkan token Fonnte dan nomor tujuan
- **Telegram:** Masukkan Bot Token dan Chat ID

### 4. Konfigurasi Syslog di MikroTik

```
/system logging action
set remote address=IP_SERVER_ANDA remote-port=514 name=remote type=remote

/system logging
add action=remote topics=critical,error,warning,info
```

---

## 🔒 Setup HTTPS (SSL Certificate) — Opsional

Jika menggunakan domain publik:

```bash
# Install certbot
sudo certbot --nginx -d domain.anda.com

# Auto-renew (sudah disetup otomatis)
sudo certbot renew --dry-run
```

---

## 🔧 Troubleshooting

### Backend tidak bisa start

```bash
# Lihat log detail
journalctl -u nocsentinel -n 100 --no-pager

# Masalah umum:
# 1. JWT_SECRET tidak di-set di .env
sudo nano /opt/noc-sentinel-v3/backend/.env
# Pastikan JWT_SECRET ada dan tidak kosong

# 2. MongoDB tidak bisa diakses
systemctl status mongod
# Coba restart
sudo systemctl restart mongod

# 3. Port 8000 sudah digunakan
netstat -tlnp | grep 8000
```

### MongoDB error "Authentication failed"

```bash
# Edit .env dan cek MONGO_URI
sudo nano /opt/noc-sentinel-v3/backend/.env

# Format yang benar:
MONGO_URI=mongodb://nocsentinel:PASSWORD@localhost:27017/nocsentinel
```

### Frontend tidak load (404 atau blank)

```bash
# Cek apakah build ada
ls /opt/noc-sentinel-v3/frontend/build/

# Jika kosong, rebuild:
cd /opt/noc-sentinel-v3/frontend
npm run build

# Restart nginx
sudo systemctl restart nginx
```

### Syslog tidak masuk

```bash
# Cek port syslog di .env
grep SYSLOG /opt/noc-sentinel-v3/backend/.env

# Cek firewall
sudo ufw status
# Harus ada: 514/udp  ALLOW

# Test kirim syslog dari MikroTik
# /tool syslog message="tes dari mikrotik"
```

---

## 🔄 Update Aplikasi

Setelah instalasi, update bisa dilakukan dengan:

```bash
# Cara cepat (script otomatis)
sudo noc-update

# Atau manual:
cd /opt/noc-sentinel-v3
git pull origin main
cd frontend && npm run build
sudo systemctl restart nocsentinel
```

Detail panduan update ada di file `CARA_UPDATE.md`.

---

## 📁 Struktur File Penting

```
/opt/noc-sentinel-v3/
├── backend/
│   ├── .env                    ← Konfigurasi (JANGAN di-share!)
│   ├── venv/                   ← Python virtual environment
│   ├── backups/                ← Backup konfigurasi MikroTik
│   └── server.py               ← Entry point backend
├── frontend/
│   └── build/                  ← Static files yang di-serve Nginx
└── install.sh                  ← Script instalasi
```

---

## 📊 Perintah Operasional

```bash
# Status semua service
systemctl status nocsentinel mongod nginx

# Restart backend
sudo systemctl restart nocsentinel

# Lihat log real-time
sudo journalctl -u nocsentinel -f

# Restart syslog (jika ada)
# syslog terintegrasi dalam backend, cukup restart nocsentinel

# Backup database manual
mongodump --uri="mongodb://nocsentinel:PASS@localhost:27017/nocsentinel" \
  --out="/backup/mongo-$(date +%Y%m%d)"

# Update aplikasi
sudo noc-update
```

---

## 📞 Support

- **GitHub Issues:** https://github.com/afani-arba/noc-sentinel-v3/issues
- **CARA_UPDATE.md:** Panduan update aplikasi
- **Log Backend:** `journalctl -u nocsentinel -n 100`
