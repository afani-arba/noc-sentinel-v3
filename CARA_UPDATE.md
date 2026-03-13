# 📦 Cara Update Aplikasi NOC Sentinel v3

Panduan lengkap untuk memperbarui NOC Sentinel v3 di server Ubuntu.

---

## ⚡ Update Cepat (1 Perintah)

Cara paling mudah — jalankan script otomatis:

```bash
cd /opt/noc-sentinel-v3
git pull origin main
sudo bash update.sh
```

Script ini akan otomatis:
- ✅ Cek & generate `JWT_SECRET` jika belum ada di `.env`
- ✅ Pull code terbaru dari GitHub
- ✅ Update Python packages
- ✅ Build ulang frontend
- ✅ Restart service backend
- ✅ Verifikasi API berjalan normal

---

## 🔧 Update Manual (Langkah per Langkah)

Jika ingin kontrol penuh, ikuti langkah-langkah ini:

### Langkah 0 — Pastikan `.env` Sudah Benar (WAJIB setelah update Maret 2026)

> **PENTING:** Setelah update ini, aplikasi **tidak bisa start** jika `JWT_SECRET` belum diisi.

```bash
# Buka file .env
nano /opt/noc-sentinel-v3/backend/.env
```

Pastikan ada baris:
```env
# Buat secret baru jika belum ada:
# python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=isi_dengan_64_karakter_hex_acak

# CORS: harus domain/IP spesifik, BUKAN "*"
CORS_ORIGINS=http://192.168.x.x:3000
```

Jika belum ada `JWT_SECRET`, buat sekarang:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# Salin output → tambahkan ke .env sebagai: JWT_SECRET=<output>
```

---

### Langkah 1 — Pull Code Terbaru dari GitHub

```bash
cd /opt/noc-sentinel-v3

# Lihat perubahan yang akan di-download (opsional)
git fetch origin
git log HEAD..origin/main --oneline

# Pull update
git pull origin main
```

Jika muncul **conflict** (rare):
```bash
git stash        # simpan perubahan lokal sementara
git pull origin main
git stash pop    # kembalikan perubahan lokal
```

---

### Langkah 2 — Update Python Dependencies

```bash
cd /opt/noc-sentinel-v3/backend

# Aktifkan virtual environment
source venv/bin/activate

# Install/update packages
pip install -r requirements.txt -q

# Keluar dari venv
deactivate
```

---

### Langkah 3 — Build Frontend (UI)

```bash
cd /opt/noc-sentinel-v3/frontend

# Install node packages (jika ada yang baru)
npm install

# Build production
npm run build

# Verifikasi build berhasil
ls -la build/index.html
```

---

### Langkah 4 — Restart Backend Service

```bash
# Restart service
sudo systemctl restart nocsentinel

# Cek status (harus "active (running)")
sudo systemctl status nocsentinel

# Jika gagal, lihat log error:
sudo journalctl -u nocsentinel -n 50 --no-pager
```

---

### Langkah 5 — Reload Nginx (untuk Frontend)

```bash
# Pastikan konfigurasi nginx benar
sudo nginx -t

# Reload (tidak disconnect user yang sedang aktif)
sudo systemctl reload nginx
```

---

### Langkah 6 — Verifikasi Aplikasi Berjalan

```bash
# Test API backend
curl -s http://localhost:8000/api/health

# Harus return: {"status":"ok","service":"NOC-Sentinel","version":"3.0.0"}
```

Buka browser → **`Ctrl+Shift+R`** (hard refresh) untuk membersihkan cache.

---

## 🚨 Troubleshooting

### Backend Gagal Start Setelah Update

**Gejala:** `sudo systemctl status nocsentinel` menunjukkan "failed"

**Cek log:**
```bash
sudo journalctl -u nocsentinel -n 50 --no-pager
```

**Solusi berdasarkan error:**

| Error di Log | Penyebab | Solusi |
|---|---|---|
| `RuntimeError: JWT_SECRET... must be set` | `JWT_SECRET` belum di-set di `.env` | Generate dan tambahkan ke `.env` (lihat Langkah 0) |
| `Connection refused` (MongoDB) | MongoDB tidak jalan | `sudo systemctl start mongod` |
| `ModuleNotFoundError` | Package Python belum diinstall | Ulangi Langkah 2 |
| `Address already in use` | Port 8000 terpakai proses lain | `sudo fuser -k 8000/tcp` lalu restart |

---

### Frontend Tidak Update (Tampilan Lama)

1. Hard refresh browser: **`Ctrl+Shift+R`** atau **`Cmd+Shift+R`** (Mac)
2. Jika masih lama, clear cache browser sepenuhnya
3. Pastikan `npm run build` sudah berhasil (ada file `build/index.html`)

---

### CORS Error di Browser (`blocked by CORS policy`)

Pastikan `.env` sudah diisi:
```env
CORS_ORIGINS=http://ip-server-anda:3000
```
Tidak boleh menggunakan `*` karena tidak kompatibel dengan autentikasi cookie.

Setelah ubah `.env`, restart:
```bash
sudo systemctl restart nocsentinel
```

---

## 📋 Cheat Sheet Perintah Berguna

```bash
# Status semua service
sudo systemctl status nocsentinel mongod nginx

# Lihat log backend real-time
sudo journalctl -u nocsentinel -f

# Restart semua service (jika ada masalah)
sudo systemctl restart nocsentinel mongod nginx

# Cek commit yang sedang berjalan
cd /opt/noc-sentinel-v3 && git log -5 --oneline

# Rollback ke commit sebelumnya
cd /opt/noc-sentinel-v3
git log --oneline -10          # pilih commit yang mau di-rollback ke sini
git checkout <commit-hash>     # rollback (detached HEAD)
# atau
git revert HEAD                # buat commit "undo"
sudo systemctl restart nocsentinel
```

---

## 📅 Riwayat Update

| Tanggal | Versi | Perubahan |
|---------|-------|-----------|
| 2026-03-13 | v3.1 | Perbaikan 17 bug kritis: ping ke device, CORS fix, task GC, route conflict `/stats/overview`, SLA heatmap, limit device 100→1000, JWT_SECRET wajib, dll |
