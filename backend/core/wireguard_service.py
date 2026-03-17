import os
import subprocess
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

WG_CONF_PATH = "/etc/wireguard/wg0.conf"

def _run_cmd(cmd: list) -> tuple[bool, str]:
    try:
        # Menjalankan perintah bash dengan sudo passwordless (asumsi server sudah dikonfigurasi)
        # atau asumsi backend NOC-Sentinel berjalan sebagai root/sudoers.
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)

def generate_wg_config(config: dict) -> bool:
    """
    Men-generate file /etc/wireguard/wg0.conf dari dictionary config.
    Format config:
      private_key: string
      client_ip: string (e.g. 10.10.10.2/24)
      server_public_key: string
      server_endpoint: string (e.g. 103.x.x.x:13231)
      allowed_ips: string (e.g. 0.0.0.0/0)
    """
    try:
        # Buat direktori jika belum ada
        os.makedirs(os.path.dirname(WG_CONF_PATH), exist_ok=True)
        
        conf_content = f"""[Interface]
PrivateKey = {config.get('private_key', '')}
Address = {config.get('client_ip', '')}

[Peer]
PublicKey = {config.get('server_public_key', '')}
Endpoint = {config.get('server_endpoint', '')}
AllowedIPs = {config.get('allowed_ips', '0.0.0.0/0')}
PersistentKeepalive = 25
"""
        with open(WG_CONF_PATH, "w") as f:
            f.write(conf_content)
        
        # Set permission to 600 for security
        os.chmod(WG_CONF_PATH, 0o600)
        return True
    except Exception as e:
        logger.error(f"Gagal mem-buat wg0.conf: {e}")
        return False

def wg_up() -> tuple[bool, str]:
    """Menyalakan tunnel wireguard (wg-quick up wg0)"""
    # Pastikan dimatikan dulu jika nyangkut
    _run_cmd(["sudo", "wg-quick", "down", "wg0"])
    
    success, output = _run_cmd(["sudo", "wg-quick", "up", "wg0"])
    if not success:
        logger.error(f"Gagal wg-quick up: {output}")
        return False, output
    return True, "Sukses menyalakan WireGuard"

def wg_down() -> tuple[bool, str]:
    """Mematikan tunnel wireguard (wg-quick down wg0)"""
    success, output = _run_cmd(["sudo", "wg-quick", "down", "wg0"])
    if not success:
        # Abaikan kalau gagal down karena emang belum jalan
        logger.warning(f"Gagal (atau sudah mati) wg-quick down: {output}")
        return False, output
    return True, "Sukses mematikan WireGuard"

def get_wg_status() -> Dict[str, Any]:
    """
    Membaca status real-time dari kernel (wg show)
    Returns dictionary status.
    """
    state = {
        "status": "offline",
        "latest_handshake": 0,
        "endpoint": "",
        "public_key": "",
        "rx_bytes": 0,
        "tx_bytes": 0
    }
    
    success, output = _run_cmd(["sudo", "wg", "show", "wg0", "dump"])
    if not success or not output:
        return state
        
    lines = output.splitlines()
    if len(lines) < 2:
        return state # Hanya ada line header
        
    # Format dump:
    # Baris 1: PublicKey PrivateKey ListenPort ... (Info Interface)
    # Baris 2+: PublicKey PresharedKey Endpoint AllowedIPs LatestHandshake TransferRx TransferTx PersistentKeepalive ...
    try:
        # Coba ambil peer info (baris 2)
        peer_line = lines[1].split("\t")
        if len(peer_line) >= 8:
            state["public_key"] = peer_line[0]
            state["endpoint"] = peer_line[2]
            hs_time = int(peer_line[4])
            state["latest_handshake"] = hs_time
            state["rx_bytes"] = int(peer_line[5])
            state["tx_bytes"] = int(peer_line[6])
            
            # Cek status online berdasarkan umut latest handshake (kalo umurnya < 3 Menit (180 detik) brati idup)
            import time
            now = int(time.time())
            if hs_time > 0 and (now - hs_time < 185):
                state["status"] = "online"
            
    except Exception as e:
        logger.error(f"Error parsing wg show dump: {e}")
        
    return state

def get_pubkey_from_privkey(private_key: str) -> str:
    """
    Generate public key from private key using 'wg pubkey' command.
    """
    if not private_key:
        return ""
    try:
        p = subprocess.Popen(['wg', 'pubkey'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = p.communicate(input=private_key)
        if p.returncode == 0:
            return stdout.strip()
        else:
            logger.error(f"Failed to generate pubkey: {stderr.strip()}")
            return ""
    except Exception as e:
        logger.error(f"Exception generating pubkey: {e}")
        return ""

def generate_private_key() -> str:
    """
    Generate a new WireGuard private key using 'wg genkey'.
    """
    try:
        result = subprocess.run(['wg', 'genkey'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            logger.error(f"Failed to generate private key: {result.stderr.strip()}")
            return ""
    except Exception as e:
        logger.error(f"Exception generating private key: {e}")
        return ""
