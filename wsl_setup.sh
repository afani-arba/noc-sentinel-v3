#!/bin/bash
# 1-Command Installer for NOC Sentinel v3 on WSL Ubuntu 22.04

set -e

echo "=========================================================="
echo "  NOC Sentinel v3 - WSL Auto-Installer"
echo "=========================================================="

# 1. Cek User Root
if [[ $EUID -ne 0 ]]; then
   echo "✗ ERROR: Script ini harus dijalankan dengan sudo."
   echo "Gunakan: sudo bash wsl_setup.sh"
   exit 1
fi

# 2. Cek Systemd di WSL (hanya jika di dalam WSL environment)
if grep -qi "microsoft" /proc/version >/dev/null 2>&1; then
    if ! systemctl is-system-running >/dev/null 2>&1 && [ "$(pidof systemd)" == "" ]; then
        echo "⚙️ Mengkonfigurasi Systemd (Wajib untuk Ubuntu WSL)..."
        
        mkdir -p /etc
        if ! grep -q "systemd=true" /etc/wsl.conf 2>/dev/null; then
            echo -e "[boot]\nsystemd=true" >> /etc/wsl.conf
        fi
        
        echo "✅ Konfigurasi systemd ditambahkan ke /etc/wsl.conf"
        echo ""
        echo "⚠️  TINDAKAN DIPERLUKAN ⚠️"
        echo "Systemd harus aktif sebelum melanjutkan instalasi."
        echo "1. Buka Windows PowerShell (bukan WSL)"
        echo "2. Jalankan perintah:  wsl --shutdown"
        echo "3. Buka kembali WSL Ubuntu Anda"
        echo "4. Jalankan ulang script ini secara otomatis:"
        echo "   curl -fsSL https://raw.githubusercontent.com/afani-arba/noc-sentinel-v3/main/wsl_setup.sh | sudo bash"
        echo "=========================================================="
        exit 0
    fi
fi

echo "✅ System environment OK. Memulai download dan instalasi..."

# 3. Jalankan installer utama secara otomatis (Unattended)
if [ ! -f "install.sh" ]; then
    curl -fsSL https://raw.githubusercontent.com/afani-arba/noc-sentinel-v3/main/install.sh -o install.sh
fi

# Bypass prompt instalasi dengan default values
# Host: localhost
# Mongo Pass: nocsentinel123!
# Admin Pass: Admin123!
# JWT Secret: (Enter untuk auto generate)
# Syslog Port: 514
# Confirm: Y

cat <<EOF | bash install.sh
localhost
nocsentinel123!
Admin123!

514
y
EOF

echo ""
echo "=========================================================="
echo "✅ Instalasi NOC Sentinel v3 di WSL Selesai!"
echo "Akses aplikasi di browser Windows Anda:"
echo "➡️  http://localhost/"
echo ""
echo "Credential Default:"
echo "Username: admin"
echo "Password: Admin123!"
echo "=========================================================="
