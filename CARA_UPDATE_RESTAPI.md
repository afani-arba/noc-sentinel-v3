# Panduan Update NOC Sentinel v3 (REST API Only) ke Server/WSL

Panduan ini berisi langkah-langkah untuk menerapkan update terbaru (yang menghapus total SNMP dan beralih ke 100% REST API dengan fitur Selective Polling dan Concurrency Limit) ke VPS atau WSL Anda.

## Prasyarat
- Akses terminal ke server/WSL (SSH atau terminal lokal).
- Pastikan Anda berada di direktori project NOC Sentinel (biasanya `/opt/noc-sentinel-v3` atau home directory Anda).

## Langkah-langkah Update

### 1. Ambil Perubahan Terbaru (Jika menggunakan Git)
Jika project Anda terhubung dengan Git lokal:
```bash
cd /path/ke/noc-sentinel-v3
git pull
```
*(Jika tidak menggunakan git, upload ulang file-file yang telah dimodifikasi, khususnya di folder `backend/core/polling.py`, `backend/requirements.txt`, dan folder `frontend/src/`)*

### 2. Update Backend (Menghapus Dependencies SNMP Lama)
Karena kita menghapus pustaka SNMP (`pysnmp-lextudio`, dsb), disarankan untuk melakukan sinkronisasi ulang environment Python:

```bash
cd backend

# Aktifkan virtual environment (jika ada)
# source venv/bin/activate

# Install ulang requirements terbaru
pip install -r requirements.txt

# (Opsional tapi disarankan) Hapus library SNMP yang sudah tidak terpakai agar bersih:
pip uninstall pysnmp-lextudio pysmi-lextudio pyasn1 pyasn1-modules -y
```

### 3. Hapus File yang Tidak Terpakai (Penting)
File polling SNMP lama sudah tidak digunakan lagi dan dapat dihapus untuk mencegah konflik.
```bash
rm -f core/snmp_poller.py
rm -f core/snmp_compat.py
```

### 4. Build Ulang Frontend
Karena kita telah menghapus elemen-elemen UI terkait SNMP (menu dropdown, status banner, tombol test SNMP), frontend harus di-build ulang:

```bash
cd ../frontend

# Install node modules jika ada perubahan (opsional tapi disarankan)
npm install

# Build production assets
npm run build
```

### 5. Restart Services
Restart service daemon NOC Sentinel Anda. Jika Anda menggunakan `pm2` atau `systemd`:

**Jika menggunakan Systemd:**
```bash
sudo systemctl restart noc-sentinel-backend
sudo systemctl restart noc-sentinel-frontend
# Atau cukup restart layanan utamanya:
sudo systemctl restart noc-sentinel
```

**Jika menggunakan PM2:**
```bash
pm2 restart all
```

**Jika menggunakan bash script tradisional (`noc-update`):**
Cukup jalankan script pembaruan otomatis yang biasa Anda pakai jika ada:
```bash
sudo noc-update
```

## Memastikan Update Berhasil
1. **Periksa UI**: Buka dashboard NOC Sentinel di browser.
2. **Menu Add/Edit Device**: Pastikan saat Anda menambah atau mengedit device, opsi untuk memasukkan **SNMP Version** dan **SNMP Community** sudah **TIDAK ADA**.
3. **Log Backend**: Anda bisa memantau log backend (`sudo journalctl -u noc-sentinel-backend -f` atau `pm2 logs`). Anda akan melihat polling berjalan menggunakan REST API:
   `Poll OK [rest_api_only]: cpu=20% ... bw=2 ifaces source=api_delta`

## Fitur Baru yang Bekerja di Background
- **Concurreny Limits & Jitter**: Backend kini memproses maksimal 50 antrian secara paralel, dan memberi jeda mili-detik (jitter) antar router. Anda tidak akan melihat CPU MikroTik melonjak drastis secara tiba-tiba walau ada 100 router.
- **Selective Polling**: API Trafik dipanggil setiap 5 detik (cepat & realtime), sedangkan info sistem/suhu/CPU diambil tiap 60 detik untuk mengurangi beban proses internal MikroTik. Data delta (Counter-wrap) dikalkulasikan murni dari API tx-byte/rx-byte.

**Update Selesai! NOC Sentinel kini akan berjalan lebih ringan dan modern hanya mengandalkan REST API bawaan RouterOS 7.**
