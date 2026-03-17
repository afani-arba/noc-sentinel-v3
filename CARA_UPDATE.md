# 📦 Cara Update NOC Sentinel v3

> **Terakhir diperbarui:** 2026-03-16
> **Commit terbaru:** `2ed5890` — Fix SNMP pysnmp-lextudio conflict (ROOT CAUSE)

---

## 🚨 SNMP Tidak Aktif / Selalu Gagal? — Perbaiki Langsung Sekarang

Jalankan perintah ini **satu per satu** di server untuk memperbaiki SNMP sekarang juga:

```bash
# Deteksi venv yang aktif
VENV="/opt/noc-sentinel-v3/backend/venv"
[ -d "/opt/noc-sentinel-v3/backend/.venv" ] && VENV="/opt/noc-sentinel-v3/backend/.venv"

# Hapus semua versi pysnmp yang konflik, lalu install ulang bersih
sudo "$VENV/bin/pip" uninstall pysnmp pysnmp-lextudio pyasn1 -y
sudo "$VENV/bin/pip" install 'pysnmp-lextudio>=1.1.0,<2.0.0' 'pyasn1>=0.5.0,<0.7.0'

# Verifikasi — harus output: SNMP OK
sudo "$VENV/bin/python" -c "from pysnmp.hlapi import SnmpEngine; print('SNMP OK ✓')"

# Restart backend agar perubahan aktif
sudo fuser -k 8000/tcp 2>/dev/null; sudo systemctl restart ARBAMonitoring
```

Setelah selesai, **hard refresh browser** (`Ctrl+Shift+R`) — banner SNMP akan hilang.

---

## ✅ Metode 1 — One-Command Update (Rekomendasi)

Jalankan satu perintah ini di server:

```bash
sudo noc-update
```

Script ini akan otomatis:
1. **Hentikan backend** dan bebaskan port 8000 (`fuser -k 8000/tcp`)
2. **Git pull** dari GitHub (`main` branch)
3. **Update Python packages** dan pastikan `pysnmp-lextudio` ada
4. **Build ulang frontend** (`npm run build`)
5. **Start ulang backend** dan verifikasi health check

> **Belum punya `noc-update`?** Install dulu:
> ```bash
> sudo bash /opt/noc-sentinel-v3/install-update.sh
> ```
> Cukup sekali saja. Setelah itu bisa pakai `sudo noc-update` kapan pun.

---

## ✅ Metode 2 — Script Manual (tanpa install)

```bash
sudo bash /opt/noc-sentinel-v3/noc-update-simple.sh
```

---

## ✅ Metode 3 — Langkah Manual (jika script gagal)

```bash
# 1. Hentikan service dan bebaskan port
sudo systemctl stop ARBAMonitoring
fuser -k 8000/tcp 2>/dev/null || true
sleep 2

# 2. Pull kode terbaru
cd /opt/noc-sentinel-v3
sudo git pull origin main

# 3. Update Python packages
VENV="/opt/noc-sentinel-v3/backend/venv"
[ -d "/opt/noc-sentinel-v3/backend/.venv" ] && VENV="/opt/noc-sentinel-v3/backend/.venv"
sudo "$VENV/bin/pip" install -r backend/requirements.txt -q

# Pastikan pysnmp ada (untuk monitoring SNMP)
sudo "$VENV/bin/pip" install 'pysnmp-lextudio>=1.1.0' -q 2>/dev/null || true

# 4. Build frontend
cd /opt/noc-sentinel-v3/frontend
sudo npm install --legacy-peer-deps -q
sudo npm run build

# 5. Start ulang service
sudo systemctl daemon-reload
sudo systemctl start ARBAMonitoring
sleep 5

# 6. Cek status
sudo systemctl status ARBAMonitoring
curl -s http://localhost:8000/api/health
```

---

## 🔍 Verifikasi Setelah Update

Setelah update selesai, pastikan:

| Cek | Perintah |
|-----|----------|
| Backend running | `sudo systemctl status ARBAMonitoring` |
| API merespons | `curl http://localhost:8000/api/health` |
| Versi benar | `curl http://localhost:8000/api/system/app-info` → harus `"version": "v3.0"` |
| Log bersih | `sudo journalctl -u ARBAMonitoring -n 50` |

---

## 🌐 Setelah Update — Hard Refresh Browser

Setelah update berhasil, lakukan **hard refresh** di browser:

- **Chrome/Firefox (Desktop):** `Ctrl + Shift + R`
- **Safari/Firefox (Mac):** `Cmd + Shift + R`
- **Mobile:** Tutup tab → buka ulang

---

## 🐛 Bugs yang Diperbaiki (Commit `df67ddb`)

| # | File | Deskripsi |
|---|------|-----------|
| 1 | `system.py` | Deklarasi variabel duplikat dihapus (VENV_PIP salah nilai) |
| 2 | `mikrotik_api.py` | 108 baris dead code (method duplikat) dihapus |
| 3 | `devices.py` | Operator precedence salah di `architecture_name` diperbaiki |
| 4 | `devices.py` | **`snmp_community` tidak tersimpan** ke database — sekarang tersimpan |
| 5 | `devices.py` | Tidak bisa kosongkan `winbox_address` — sekarang bisa (`null`) |
| 6 | `system.py` | Versi hardcoded `v2.5` → `v3.0` |

> **Bug #4 penting!** Jika sebelumnya SNMP community bukan `public`, device perlu
> di-edit ulang di halaman Devices untuk menyimpan community string yang benar.

---

## ❓ Troubleshooting

**Backend tidak mau start setelah update:**
```bash
# Lihat log detail
sudo journalctl -u ARBAMonitoring -n 100 --no-pager

# Paksa bunuh proses bertabrakan di port 8000
sudo fuser -k 8000/tcp
sudo fuser -k -KILL 8000/tcp
sudo systemctl start ARBAMonitoring
```

**Port 8000 masih busy:**
```bash
sudo lsof -ti:8000 | xargs -r kill -9
sudo systemctl start ARBAMonitoring
```

**Frontend masih tampil versi lama (cache):**
```bash
# Di server — hapus build lama
sudo rm -rf /opt/noc-sentinel-v3/frontend/build
cd /opt/noc-sentinel-v3/frontend
sudo npm run build
sudo systemctl reload nginx
```
