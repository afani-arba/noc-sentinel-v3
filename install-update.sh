#!/bin/bash
# ╔═══════════════════════════════════════════════════════╗
# ║  NOC Sentinel v3 — Install noc-update command        ║
# ║  Jalankan SEKALI di server:                          ║
# ║    sudo bash /opt/noc-sentinel-v3/install-update.sh  ║
# ╚═══════════════════════════════════════════════════════╝

SRC="/opt/noc-sentinel-v3/noc-update"
DST="/usr/local/bin/noc-update"

[[ $EUID -ne 0 ]] && { echo "❌ Jalankan sebagai root: sudo bash install-update.sh"; exit 1; }
[[ ! -f "$SRC" ]] && { echo "❌ File $SRC tidak ditemukan. Pastikan git pull sudah dilakukan."; exit 1; }

cp -f "$SRC" "$DST"
chmod +x "$DST"
echo "✅ noc-update terinstall di $DST"
echo "   Gunakan: sudo noc-update"
