"""
Unified MikroTik API client — Hybrid Monitoring.
=================================================
Dua implementasi dengan interface yang identik:
  - MikroTikRestAPI     : RouterOS 7.x — REST API (port 443/80)
  - MikroTikLegacyAPI   : RouterOS 6.x — API Protocol (port 8728/8729)

Factory:
  get_api_client(device) → pilih class berdasarkan device['api_mode']
  discover_device(device) → auto-detect mode dan simpan ke DB
"""
import ssl
import httpx
import asyncio
import logging
import urllib3
import routeros_api

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


def parse_host_port(ip_address: str, default_port: int = None):
    """
    Parse 'host' or 'host:port' format dari field ip_address.
    Support format:
      - '192.168.1.1'          → ('192.168.1.1', default_port)
      - '192.168.1.1:7701'     → ('192.168.1.1', 7701)
      - '103.157.116.29:7701'  → ('103.157.116.29', 7701)

    Returns: (host: str, port: int|None)
    """
    if not ip_address:
        return ip_address, default_port

    ip_address = str(ip_address).strip()

    # Cek apakah mengandung port (host:port)
    if ':' in ip_address:
        parts = ip_address.rsplit(':', 1)
        try:
            port = int(parts[1])
            return parts[0], port
        except ValueError:
            pass  # bukan port valid, kembali sebagai host saja

    return ip_address, default_port


# ── Global HTTPX Client Pool ───────────────────────────────────────────────
# Untuk persistent connections (keep-alive) dan mencegah overhead koneksi ulang.
_httpx_clients = {}

def _get_httpx_client(base_url: str, use_ssl: bool) -> httpx.AsyncClient:
    key = (base_url, use_ssl)
    if key not in _httpx_clients:
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("ALL:@SECLEVEL=0")
        except ssl.SSLError:
            pass
        try:
            ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        except (AttributeError, ValueError):
            pass
        try:
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        except AttributeError:
            pass
            
        _httpx_clients[key] = httpx.AsyncClient(
            verify=ctx if use_ssl else False,
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
        )
    return _httpx_clients[key]



# ── Base interface ──
class MikroTikBase:
    # ── Connection ──
    async def test_connection(self): raise NotImplementedError

    # ── Polling/Monitoring — default aman (return kosong) ──
    # Subclass yang tidak implement tidak akan menyebabkan AttributeError
    async def get_system_resource(self): return {}
    async def get_system_health(self):   return {}  # Override di subclass
    async def list_interfaces(self):     return []
    async def get_isp_interfaces(self):  return []
    async def get_interface_traffic(self, interface_name="ether1", duration=1): return {}
    async def ping_host(self, address="8.8.8.8", count=4): return []

    # ── PPPoE ──
    async def list_pppoe_secrets(self): raise NotImplementedError
    async def create_pppoe_secret(self, data): raise NotImplementedError
    async def update_pppoe_secret(self, mt_id, data): raise NotImplementedError
    async def delete_pppoe_secret(self, mt_id): raise NotImplementedError
    async def list_pppoe_active(self): raise NotImplementedError
    async def disable_pppoe_user(self, username): raise NotImplementedError
    async def enable_pppoe_user(self, username): raise NotImplementedError

    # ── Hotspot ──
    async def list_hotspot_users(self): raise NotImplementedError
    async def create_hotspot_user(self, data): raise NotImplementedError
    async def update_hotspot_user(self, mt_id, data): raise NotImplementedError
    async def delete_hotspot_user(self, mt_id): raise NotImplementedError
    async def list_hotspot_active(self): raise NotImplementedError
    async def disable_hotspot_user(self, username): raise NotImplementedError
    async def enable_hotspot_user(self, username): raise NotImplementedError
    async def list_pppoe_profiles(self): raise NotImplementedError
    async def list_hotspot_profiles(self): raise NotImplementedError
    async def list_hotspot_servers(self): raise NotImplementedError


# ═══════════════════════════════════════════════════════════
# RouterOS 7+ REST API
# ═══════════════════════════════════════════════════════════
class MikroTikRestAPI(MikroTikBase):
    def __init__(self, host, username, password, port=443, use_ssl=True):
        # Support format host:port — parse terlebih dahulu agar tidak double-port
        parsed_host, parsed_port = parse_host_port(host, default_port=port)
        self.host = parsed_host
        self.port = parsed_port if parsed_port is not None else port
        self.use_ssl = use_ssl

        scheme = "https" if use_ssl else "http"
        self.base_url = f"{scheme}://{self.host}:{self.port}/rest"
        self.auth = (username, password)
        self.verify = False
        self.timeout = 30

    async def _async_req(self, method, path, data=None, timeout=None):
        url = f"{self.base_url}/{path}"
        req_timeout = timeout if timeout is not None else self.timeout
        client = _get_httpx_client(self.base_url, self.use_ssl)
        
        logger.info(f"REST API request: {method} {url} (timeout={req_timeout}s)")
        try:
            resp = await client.request(
                method, url, auth=self.auth, json=data, timeout=req_timeout
            )
            logger.info(f"REST API response: {resp.status_code}")
            
            if resp.status_code == 401:
                raise Exception("Authentication failed - check API username/password")
            if resp.status_code == 400:
                detail = resp.json() if resp.content else {}
                raise Exception(f"Bad request: {detail.get('detail', detail.get('message', resp.text))}")
            if resp.status_code == 404:
                raise Exception(f"Endpoint tidak ditemukan (404): {path} - pastikan RouterOS mendukung endpoint ini")
                
            resp.raise_for_status()
            return resp.json() if resp.content else {}
            
        except httpx.ConnectError as e:
            logger.error(f"Connection Error to {url}: {e}")
            error_msg = str(e)
            if "refused" in error_msg.lower():
                raise Exception(f"Connection refused - pastikan www service aktif di port {self.port} dan tidak ada firewall yang memblokir")
            elif "route to host" in error_msg.lower():
                raise Exception(f"No route to host - periksa IP address dan jaringan")
            elif "ssl" in error_msg.lower() or "handshake" in error_msg.lower():
                raise Exception(f"SSL Handshake gagal ke {self.host}:{self.port}. Coba ganti ke HTTP (port 80) di konfigurasi device.")
            else:
                raise Exception(f"Tidak dapat terhubung ke {self.host}:{self.port} - pastikan: 1) www service aktif, 2) port {self.port} tidak diblokir firewall, 3) IP server monitoring diizinkan di MikroTik")
        except httpx.TimeoutException:
            raise Exception(f"Connection timeout ke {self.host}:{self.port} - periksa: 1) Firewall MikroTik, 2) www service address restriction, 3) Koneksi jaringan")
        except Exception as e:
            if any(k in str(e) for k in ["Authentication", "Bad request", "Cannot connect", "timeout", "SSL Error", "Connection refused", "No route"]):
                raise
            raise Exception(f"REST API error: {e}")

    async def test_connection(self):
        """
        Test koneksi REST API MikroTik ROS 7+.
        Coba 3 endpoint bertingkat: system/identity → system/resource → ip/address
        Jika semua 404: REST API tidak aktif di device (www service belum diaktifkan).
        """
        endpoints = [
            ("system/identity",  lambda r: r.get("name", "MikroTik")),
            ("system/resource",  lambda r: r.get("board-name", r.get("platform", "MikroTik"))),
            ("ip/address",       lambda r: "MikroTik" if isinstance(r, list) else r.get("name", "MikroTik")),
        ]
        last_error = ""
        all_404    = True

        for path, extract_name in endpoints:
            try:
                r = await self._async_req("GET", path)
                identity = extract_name(r) if isinstance(r, (dict, list)) else "MikroTik"
                return {
                    "success":  True,
                    "identity": identity,
                    "mode":     "REST API (RouterOS 7+)",
                    "endpoint": path,
                }
            except Exception as e:
                err_str = str(e)
                last_error = err_str
                # Jika bukan 404, hentikan loop — ini error koneksi bukan REST API disabled
                if "404" not in err_str:
                    all_404 = False
                    break

        if all_404:
            # Semua endpoint 404 = REST API (www service) tidak aktif di device
            return {
                "success": False,
                "error":   (
                    f"REST API tidak aktif di {self.host}:{self.port}. "
                    "Aktifkan www service di MikroTik: "
                    "IP → Services → www → Enable, "
                    "atau jalankan: /ip service enable www"
                ),
                "mode": "REST API (RouterOS 7+)",
            }

        # Error koneksi lain (timeout, auth fail, SSL, refused)
        return {"success": False, "error": last_error, "mode": "REST API (RouterOS 7+)"}


    # ── System Resource (ROS 7.x REST API) ──
    async def get_system_resource(self):
        """Ambil CPU, memory, uptime dari /rest/system/resource."""
        try:
            return await self._async_req("GET", "system/resource")
        except Exception:
            return {}

    # ── System Health (ROS 7.x: temperature, voltage, power) ──
    async def get_system_health(self):
        """
        Ambil data sensor hardware dari /rest/system/health.
        Field nyata dari MikroTik ROS 7.x:
          {name: cpu-temperature, value: 47, type: C}
          {name: sfp-temperature, value: 38, type: C}
          {name: switch-temperature, value: 39, type: C}
          {name: board-temperature1, value: 39, type: C}
          {name: fan1-speed, value: 4080, type: RPM}
          {name: fan-state, value: ok}
          {name: psu1-state, value: fail}
          {name: psu2-state, value: ok}
          {name: voltage, value: 240, type: dV}   (some devices)
        """
        try:
            items = await self._async_req("GET", "system/health")
            if not isinstance(items, list):
                return {}

            result = {
                "cpu_temp": 0,
                "board_temp": 0,
                "sfp_temp": 0,
                "switch_temp": 0,
                "voltage": 0,
                "power": 0,
                "fans": {},        # {fan1: 4080, fan2: 4020, ...}
                "fan_state": "",   # "ok" / "fail"
                "psu": {},         # {psu1: "ok", psu2: "fail", ...}
                "extra_temps": {}, # {sfp: 38, switch: 39, ...}
            }

            for item in items:
                name = (item.get("name") or "").lower()
                raw_val = item.get("value", "")
                unit = (item.get("type") or "").upper()

                # Try numeric conversion
                try:
                    num_val = float(str(raw_val))
                except (ValueError, TypeError):
                    num_val = None

                # ── Temperatures ──────────────────────────────────
                if name == "cpu-temperature":
                    result["cpu_temp"] = num_val or 0

                elif name.startswith("board-temperature"):
                    # board-temperature, board-temperature1, board-temperature2
                    if result["board_temp"] == 0:
                        result["board_temp"] = num_val or 0

                elif name == "sfp-temperature":
                    result["sfp_temp"] = num_val or 0
                    result["extra_temps"]["sfp"] = num_val or 0

                elif name == "switch-temperature":
                    result["switch_temp"] = num_val or 0
                    result["extra_temps"]["switch"] = num_val or 0

                elif "temperature" in name:
                    # catch-all for other temperature sensors
                    key = name.replace("-temperature", "").replace("-temp", "")
                    result["extra_temps"][key] = num_val or 0
                    if result["board_temp"] == 0:
                        result["board_temp"] = num_val or 0

                # ── Voltage ───────────────────────────────────────
                elif "voltage" in name:
                    if num_val is not None:
                        # MikroTik may return dV (deci-volt): 240 dV = 24.0 V
                        voltage = num_val / 10.0 if unit == "DV" or num_val > 100 else num_val
                        result.setdefault("voltage", round(voltage, 1))

                # ── Power ─────────────────────────────────────────
                elif "power" in name and "psu" not in name:
                    result.setdefault("power", num_val or 0)

                # ── Current ───────────────────────────────────────
                elif name == "current":
                    result["current"] = num_val or 0

                # ── Fan speed (fan1-speed, fan2-speed ...) ────────
                elif name.endswith("-speed") and "fan" in name:
                    fan_key = name.replace("-speed", "")  # fan1, fan2, ...
                    result["fans"][fan_key] = int(num_val) if num_val else 0

                # ── Fan state (ok / fail) ─────────────────────────
                elif name == "fan-state":
                    result["fan_state"] = str(raw_val).lower()

                # ── PSU state (psu1-state, psu2-state) ───────────
                elif name.endswith("-state") and "psu" in name:
                    psu_key = name.replace("-state", "")  # psu1, psu2, ...
                    result["psu"][psu_key] = str(raw_val).lower()

            return result
        except Exception:
            return {}

    # ── Interface List ──
    async def list_interfaces(self):
        """List semua interface beserta status running/disabled."""
        try:
            ifaces = await self._async_req("GET", "interface")
            return ifaces if isinstance(ifaces, list) else []
        except Exception:
            return []

    async def list_pppoe_active(self):
        """Ambil list PPPoE active di RouterOS 7."""
        try:
            items = await self._async_req("GET", "ppp/active")
            return items if isinstance(items, list) else []
        except Exception:
            return []

    async def list_hotspot_active(self):
        """Ambil list Hotspot active di RouterOS 7."""
        try:
            items = await self._async_req("GET", "ip/hotspot/active")
            return items if isinstance(items, list) else []
        except Exception:
            return []

    async def get_isp_interfaces(self):
        """
        Return list of interface names that are marked as ISP/WAN/INPUT uplinks
        via their 'comment' field in MikroTik.

        Keywords checked (case-insensitive) — LOCKED IN CODE (ISP1..ISP20, WAN, INPUT):
          isp, isp1..isp20, wan, wan1..wan20, input, input1..input20,
          uplink, upstream, internet, gateway

        Multi-ISP: semua interface yang match akan dikembalikan (support sampai 20 ISP).
        Falls back to empty list if none found (caller should fallback to 'all physical').
        """
        # ── Keyword ISP detection — dikunci di kode ──────────────────────────────
        ISP_KEYWORDS = (
            "isp",
            *[f"isp{i}" for i in range(1, 21)],   # isp1 .. isp20
            "wan",
            *[f"wan{i}" for i in range(1, 21)],   # wan1 .. wan20
            "input",
            *[f"input{i}" for i in range(1, 21)], # input1 .. input20
            "uplink", "upstream", "internet", "gateway",
        )
        try:
            ifaces = await self._async_req("GET", "interface")
            if not isinstance(ifaces, list):
                return []
            matched = []
            for iface in ifaces:
                comment = str(iface.get("comment", "") or "").lower()
                name = iface.get("name", "")
                if name and any(kw in comment for kw in ISP_KEYWORDS):
                    matched.append(name)
            return matched
        except Exception:
            return []

    # ── Interface Traffic (monitor-traffic via POST, ROS 7.x) ──
    async def get_interface_traffic(self, interface_name: str = "ether1", duration: int = 1):
        """
        Ambil traffic realtime via /rest/interface/monitor-traffic.
        ROS 7.x: POST dengan body {"interface": "ether1", "once": true}
        CATATAN: ROS 7.16+ wajib pakai boolean True (bukan empty string "")
        Return: {"rx-bits-per-second": ..., "tx-bits-per-second": ...}
        """
        try:
            result = await asyncio.wait_for(
                self._async_req(
                    "POST", "interface/monitor-traffic",
                    {"interface": interface_name, "once": True}  # True bukan ""
                ),
                timeout=8.0
            )
            if isinstance(result, list):
                return result[0] if result else {}
            return result
        except Exception:
            return {}

    async def get_all_interface_stats(self):
        """
        ROS 7: Ambil stats interface fisik (rx-byte, tx-byte) + deteksi ISP interface.
        Return: {
            'stats':          {iface_name: {rx-bytes: int, tx-bytes: int, virtual: bool}},
            'isp_interfaces': [nama-nama interface ISP/WAN yang terdeteksi]
        }
        """
        _SKIP_TYPES = {
            "bridge", "vlan", "pppoe-out", "pppoe-in", "l2tp", "pptp",
            "ovpn-client", "ovpn-server", "sstp-client", "sstp-server",
            "gre", "eoip", "eoipv6", "veth", "wireguard", "loopback",
            "6to4", "ipip", "ipip6", "dummy"
        }
        _SKIP_PREFIXES = ("lo", "docker", "veth", "tun", "tap", "<")
        _ISP_KEYWORDS = (
            "isp", *[f"isp{i}" for i in range(1, 21)],
            "wan", *[f"wan{i}" for i in range(1, 21)],
            "input", *[f"input{i}" for i in range(1, 21)],
            "uplink", "upstream", "internet", "gateway",
        )
        try:
            items = await self._async_req("GET", "interface")
            if not isinstance(items, list):
                return {"stats": {}, "isp_interfaces": [], "isp_comments": {}}

            stats = {}
            isp_ifaces = []
            isp_comments = {}

            for item in items:
                name = item.get("name", "")
                itype = str(item.get("type", "")).lower()
                if not name:
                    continue

                raw_comment = str(item.get("comment", "") or "")
                comment = raw_comment.lower()
                if any(kw in comment for kw in _ISP_KEYWORDS):
                    isp_ifaces.append(name)
                    isp_comments[name] = raw_comment

                is_virtual = itype in _SKIP_TYPES or name.lower().startswith(_SKIP_PREFIXES)
                if is_virtual:
                    continue

                stats[name] = {
                    "rx-bytes": int(item.get("rx-byte", 0) or 0),
                    "tx-bytes": int(item.get("tx-byte", 0) or 0),
                }

            return {"stats": stats, "isp_interfaces": isp_ifaces, "isp_comments": isp_comments}
        except Exception as e:
            logger.debug(f"get_all_interface_stats REST gagal: {e}")
            return {"stats": {}, "isp_interfaces": [], "isp_comments": {}}

    # ── IP Address List ──
    async def list_ip_addresses(self):
        """List semua IP address yang dikonfigurasi."""
        try:
            return await self._async_req("GET", "ip/address")
        except Exception:
            return []

    # ── OSPF ──
    async def list_ospf_neighbors(self):
        try:
            return await self._async_req("GET", "routing/ospf/neighbor")
        except Exception:
            return []

    async def list_ospf_instances(self):
        try:
            return await self._async_req("GET", "routing/ospf/instance")
        except Exception:
            return []

    # ── IP Routes ──
    async def list_ip_routes(self, limit: int = 200):
        try:
            routes = await self._async_req("GET", "ip/route")
            return routes[:limit] if isinstance(routes, list) else []
        except Exception:
            return []

    # ── Active Connections ──
    async def list_connections(self, limit: int = 500):
        try:
            conns = await self._async_req("GET", "ip/firewall/connection")
            return conns[:limit] if isinstance(conns, list) else []
        except Exception:
            return []

    # ── Firewall ──
    async def list_firewall_filter(self):
        try:
            return await self._async_req("GET", "ip/firewall/filter")
        except Exception:
            return []

    async def list_firewall_nat(self):
        try:
            return await self._async_req("GET", "ip/firewall/nat")
        except Exception:
            return []

    async def list_firewall_mangle(self):
        try:
            return await self._async_req("GET", "ip/firewall/mangle")
        except Exception:
            return []

    # ── PPPoE (ROS 7.x REST API) ──────────────────────────────────────────────
    # Endpoint: /rest/ppp/secret  (PPPoE user secrets)
    #           /rest/ppp/active  (active PPPoE connections)
    #           /rest/ppp/profile (PPP profiles)

    async def list_pppoe_secrets(self):
        """List PPPoE secrets (users) dari /ppp/secret."""
        try:
            items = await self._async_req("GET", "ppp/secret")
            return items if isinstance(items, list) else []
        except Exception as e:
            logger.warning(f"list_pppoe_secrets REST failed: {e}")
            return []

    async def create_pppoe_secret(self, data):
        """Buat PPPoE secret baru."""
        try:
            return await self._async_req("PUT", "ppp/secret", data)
        except Exception as e:
            raise Exception(f"Gagal membuat PPPoE user: {e}")

    async def update_pppoe_secret(self, mt_id, data):
        """Update PPPoE secret berdasarkan .id MikroTik."""
        try:
            # REST API ROS7: PATCH /ppp/secret/<mt_id>
            return await self._async_req("PATCH", f"ppp/secret/{mt_id}", data)
        except Exception as e:
            raise Exception(f"Gagal mengupdate PPPoE user: {e}")

    async def delete_pppoe_secret(self, mt_id):
        """Hapus PPPoE secret berdasarkan .id MikroTik."""
        try:
            return await self._async_req("DELETE", f"ppp/secret/{mt_id}")
        except Exception as e:
            raise Exception(f"Gagal menghapus PPPoE user: {e}")

    async def list_pppoe_active(self):
        """List koneksi PPPoE yang aktif dari /ppp/active."""
        try:
            items = await self._async_req("GET", "ppp/active")
            return items if isinstance(items, list) else []
        except Exception as e:
            logger.warning(f"list_pppoe_active REST failed: {e}")
            return []

    async def disable_pppoe_user(self, username):
        """Disable PPPoE user berdasarkan username."""
        try:
            secrets = await self.list_pppoe_secrets()
            for s in secrets:
                if s.get("name") == username:
                    mt_id = s.get(".id", "")
                    return await self._async_req("PATCH", f"ppp/secret/{mt_id}", {"disabled": "true"})
            raise Exception(f"PPPoE user '{username}' tidak ditemukan")
        except Exception as e:
            raise Exception(f"Gagal disable PPPoE user: {e}")

    async def enable_pppoe_user(self, username):
        """Enable PPPoE user berdasarkan username."""
        try:
            secrets = await self.list_pppoe_secrets()
            for s in secrets:
                if s.get("name") == username:
                    mt_id = s.get(".id", "")
                    return await self._async_req("PATCH", f"ppp/secret/{mt_id}", {"disabled": "false"})
            raise Exception(f"PPPoE user '{username}' tidak ditemukan")
        except Exception as e:
            raise Exception(f"Gagal enable PPPoE user: {e}")

    # ── PPP Profiles ──────────────────────────────────────────────────────────
    async def list_pppoe_profiles(self):
        """List PPP profiles dari /ppp/profile."""
        try:
            items = await self._async_req("GET", "ppp/profile")
            return items if isinstance(items, list) else []
        except Exception as e:
            logger.warning(f"list_pppoe_profiles REST failed: {e}")
            return []

    # ── Hotspot (ROS 7.x REST API) ────────────────────────────────────────────
    async def list_hotspot_users(self):
        try:
            items = await self._async_req("GET", "ip/hotspot/user")
            return items if isinstance(items, list) else []
        except Exception:
            return []

    async def create_hotspot_user(self, data):
        return await self._async_req("PUT", "ip/hotspot/user", data)

    async def update_hotspot_user(self, mt_id, data):
        return await self._async_req("PATCH", f"ip/hotspot/user/{mt_id}", data)

    async def delete_hotspot_user(self, mt_id):
        return await self._async_req("DELETE", f"ip/hotspot/user/{mt_id}")

    async def list_hotspot_active(self):
        try:
            items = await self._async_req("GET", "ip/hotspot/active")
            return items if isinstance(items, list) else []
        except Exception:
            return []

    async def disable_hotspot_user(self, username):
        users = await self.list_hotspot_users()
        for u in users:
            if u.get("name") == username:
                mt_id = u.get(".id", "")
                return await self._async_req("PATCH", f"ip/hotspot/user/{mt_id}", {"disabled": "true"})
        raise Exception(f"Hotspot user '{username}' tidak ditemukan")

    async def enable_hotspot_user(self, username):
        users = await self.list_hotspot_users()
        for u in users:
            if u.get("name") == username:
                mt_id = u.get(".id", "")
                return await self._async_req("PATCH", f"ip/hotspot/user/{mt_id}", {"disabled": "false"})
        raise Exception(f"Hotspot user '{username}' tidak ditemukan")

    async def list_hotspot_profiles(self):
        try:
            items = await self._async_req("GET", "ip/hotspot/user/profile")
            return items if isinstance(items, list) else []
        except Exception:
            return []

    async def list_hotspot_servers(self):
        try:
            items = await self._async_req("GET", "ip/hotspot")
            return items if isinstance(items, list) else []
        except Exception:
            return []

    # ── Ping (ROS 7.x REST API) ──
    async def ping_host(self, address: str = "8.8.8.8", count: int = 4, interface: str = ""):
        """
        Melakukan ping dari router ke target address via /rest/ping.
        Mengembalikan list of dict response ping.
        """
        try:
            # ROS 7: coba integer count terlebih dahulu, lalu string jika gagal
            payload = {"address": address, "count": int(count)}
            if interface:
                payload["interface"] = interface
            
            items = await self._async_req("POST", "ping", payload)
            
            # Beberapa versi ROS7 mengembalikan dict tunggal dengan "avg-rtt" (aggregated)
            # Versi lain mengembalikan list per-packet [{time, status}, ...]
            if isinstance(items, dict):
                if "ret" in items:
                    items = items["ret"]
                elif "avg-rtt" in items or "time" in items:
                    # Aggregated result → convert ke list format
                    items = [items]
                else:
                    items = []
                    
            return items if isinstance(items, list) else [items] if items else []
        except Exception as e:
            logger.warning(f"ping_host REST gagal ke {address}: {e}")
            return []



# ═══════════════════════════════════════════════════════════
# RouterOS 6.x — MikroTik API Protocol (port 8728/8729)
# Nama class: MikroTikLegacyAPI
# Alias backward-compat: MikroTikRouterAPI
# ═══════════════════════════════════════════════════════════
class MikroTikLegacyAPI(MikroTikBase):
    def __init__(self, host, username, password, port=8728, use_ssl=False, plaintext_login=True):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.use_ssl = use_ssl
        self.plaintext_login = plaintext_login

    def _get_connection(self):
        """Create a new connection to the router."""
        try:
            pool = routeros_api.RouterOsApiPool(
                host=self.host,
                username=self.username,
                password=self.password,
                port=self.port,
                use_ssl=self.use_ssl,
                ssl_verify=False,
                plaintext_login=self.plaintext_login,
            )
            return pool
        except Exception as e:
            raise Exception(f"Cannot connect to MikroTik API at {self.host}:{self.port} - {e}")

    def _execute(self, callback):
        """Execute a callback with a connection, ensuring cleanup."""
        pool = self._get_connection()
        try:
            api = pool.get_api()
            result = callback(api)
            return result
        finally:
            try:
                pool.disconnect()
            except Exception:
                pass

    def _list_resource(self, path):
        def cb(api):
            resource = api.get_resource(path)
            return resource.get()
        return self._execute(cb)

    def _add_resource(self, path, data):
        def cb(api):
            resource = api.get_resource(path)
            # routeros_api uses keyword arguments
            resource.add(**data)
            return {"success": True}
        return self._execute(cb)

    def _set_resource(self, path, mt_id, data):
        def cb(api):
            resource = api.get_resource(path)
            resource.set(id=mt_id, **data)
            return {"success": True}
        return self._execute(cb)

    def _remove_resource(self, path, mt_id):
        def cb(api):
            resource = api.get_resource(path)
            resource.remove(id=mt_id)
            return {"success": True}
        return self._execute(cb)

    # Normalize RouterOS 6 API response to match REST API format
    def _normalize_items(self, items):
        """RouterOS API returns list of dicts with 'id' key. Normalize to match REST format."""
        result = []
        for item in items:
            normalized = {}
            for k, v in item.items():
                normalized[k] = v
            # Ensure .id field exists (RouterOS API uses 'id')
            if "id" in normalized and ".id" not in normalized:
                normalized[".id"] = normalized["id"]
            result.append(normalized)
        return result

    async def test_connection(self):
        try:
            def cb(api):
                resource = api.get_resource("/system/identity")
                return resource.get()
            result = await asyncio.to_thread(self._execute, cb)
            name = result[0].get("name", "") if result else ""
            return {"success": True, "identity": name, "mode": "API Protocol (RouterOS 6+)"}
        except Exception as e:
            return {"success": False, "error": str(e), "mode": "API Protocol (RouterOS 6+)"}

    # ── PPPoE ──
    async def list_pppoe_secrets(self):
        items = await asyncio.to_thread(self._list_resource, "/ppp/secret")
        return self._normalize_items(items)

    async def create_pppoe_secret(self, data):
        return await asyncio.to_thread(self._add_resource, "/ppp/secret", data)

    async def update_pppoe_secret(self, mt_id, data):
        return await asyncio.to_thread(self._set_resource, "/ppp/secret", mt_id, data)

    async def delete_pppoe_secret(self, mt_id):
        return await asyncio.to_thread(self._remove_resource, "/ppp/secret", mt_id)

    async def list_pppoe_active(self):
        items = await asyncio.to_thread(self._list_resource, "/ppp/active")
        return self._normalize_items(items)

    async def disable_pppoe_user(self, username):
        secrets = await self.list_pppoe_secrets()
        for s in secrets:
            if s.get("name") == username:
                mt_id = s.get(".id") or s.get("id", "")
                return await asyncio.to_thread(self._set_resource, "/ppp/secret", mt_id, {"disabled": "true"})
        raise Exception(f"PPPoE user '{username}' tidak ditemukan")

    async def enable_pppoe_user(self, username):
        secrets = await self.list_pppoe_secrets()
        for s in secrets:
            if s.get("name") == username:
                mt_id = s.get(".id") or s.get("id", "")
                return await asyncio.to_thread(self._set_resource, "/ppp/secret", mt_id, {"disabled": "false"})
        raise Exception(f"PPPoE user '{username}' tidak ditemukan")

    # ── Hotspot ──
    async def list_hotspot_users(self):
        items = await asyncio.to_thread(self._list_resource, "/ip/hotspot/user")
        return self._normalize_items(items)

    async def create_hotspot_user(self, data):
        return await asyncio.to_thread(self._add_resource, "/ip/hotspot/user", data)

    async def update_hotspot_user(self, mt_id, data):
        return await asyncio.to_thread(self._set_resource, "/ip/hotspot/user", mt_id, data)

    async def delete_hotspot_user(self, mt_id):
        return await asyncio.to_thread(self._remove_resource, "/ip/hotspot/user", mt_id)

    async def list_hotspot_active(self):
        items = await asyncio.to_thread(self._list_resource, "/ip/hotspot/active")
        return self._normalize_items(items)

    async def disable_hotspot_user(self, username):
        users = await self.list_hotspot_users()
        for u in users:
            if u.get("name") == username:
                mt_id = u.get(".id") or u.get("id", "")
                return await asyncio.to_thread(self._set_resource, "/ip/hotspot/user", mt_id, {"disabled": "true"})
        raise Exception(f"Hotspot user '{username}' tidak ditemukan")

    async def enable_hotspot_user(self, username):
        users = await self.list_hotspot_users()
        for u in users:
            if u.get("name") == username:
                mt_id = u.get(".id") or u.get("id", "")
                return await asyncio.to_thread(self._set_resource, "/ip/hotspot/user", mt_id, {"disabled": "false"})
        raise Exception(f"Hotspot user '{username}' tidak ditemukan")

    async def list_pppoe_profiles(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ppp/profile")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_hotspot_profiles(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/hotspot/user-profile")
            return self._normalize_items(items)
        except Exception:
            try:
                items = await asyncio.to_thread(self._list_resource, "/ip/hotspot/user/profile")
                return self._normalize_items(items)
            except Exception:
                return []

    async def list_hotspot_servers(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/hotspot")
            return self._normalize_items(items)
        except Exception:
            return []

    # ── System Resource ──
    async def get_system_resource(self):
        """Ambil CPU, memory, uptime dari /system/resource."""
        try:
            items = await asyncio.to_thread(self._list_resource, "/system/resource")
            return items[0] if items else {}
        except Exception:
            return {}

    async def get_system_health(self):
        """
        ROS6: Ambil data health dari /system/health (temperature, voltage).
        Setiap item: {name: 'temperature'|'voltage', value: '30', type: 'C'|'V'}
        Return dict normalized: {cpu_temp, board_temp, voltage, ..., raw: [...]}
        """
        try:
            items = await asyncio.to_thread(self._list_resource, "/system/health")
            if not items:
                return {}

            result = {
                "cpu_temp": 0.0,
                "board_temp": 0.0,
                "sfp_temp": 0.0,
                "switch_temp": 0.0,
                "voltage": 0.0,
                "power": 0.0,
                "fans": {},
                "psu": {},
                "extra_temps": {},
                "raw": items,
            }

            def _f(v):
                try: return float(str(v).strip())
                except Exception: return 0.0

            for entry in items:
                name  = str(entry.get("name", "")).lower().strip()
                value = entry.get("value", "0")
                typ   = str(entry.get("type", "")).upper().strip()

                if typ == "C":  # Temperature
                    if "cpu" in name and "board" not in name:
                        result["cpu_temp"] = _f(value)
                    elif "board" in name:
                        result["board_temp"] = _f(value)
                    elif "sfp" in name or "optical" in name:
                        result["sfp_temp"] = _f(value)
                    elif "switch" in name or "chip" in name:
                        result["switch_temp"] = _f(value)
                    elif "temperature" == name:
                        # Generic 'temperature' entry — biasanya board temp
                        if result["board_temp"] == 0:
                            result["board_temp"] = _f(value)
                        else:
                            result["extra_temps"][name] = _f(value)
                    else:
                        result["extra_temps"][name] = _f(value)

                elif typ == "V":  # Voltage
                    if result["voltage"] == 0:
                        result["voltage"] = _f(value)

                elif typ == "W":  # Power
                    result["power"] = _f(value)

                elif typ == "RPM":
                    result["fans"][name] = int(_f(value))

                elif typ == "":
                    # Beberapa ROS6 tidak ada tipe, tebak dari nama
                    if "fan" in name:
                        result["fans"][name] = int(_f(value))
                    elif "volt" in name:
                        if result["voltage"] == 0:
                            result["voltage"] = _f(value)

            return result
        except Exception as e:
            logger.debug(f"get_system_health ROS6 gagal: {e}")
            return {}

    # ── Interface List ──
    async def list_interfaces(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/interface")
            return self._normalize_items(items)
        except Exception:
            return []

    async def get_isp_interfaces(self):
        """
        Return list of interface names that are marked as ISP/WAN/INPUT uplinks
        via their 'comment' field in MikroTik.

        Keywords checked (case-insensitive) — LOCKED IN CODE (ISP1..ISP20, WAN, INPUT):
          isp, isp1..isp20, wan, wan1..wan20, input, input1..input20,
          uplink, upstream, internet, gateway

        Multi-ISP: semua interface yang match dikembalikan (support sampai 20 ISP).
        """
        # ── Keyword ISP detection — dikunci di kode ──────────────────────────────
        ISP_KEYWORDS = (
            "isp",
            *[f"isp{i}" for i in range(1, 21)],   # isp1 .. isp20
            "wan",
            *[f"wan{i}" for i in range(1, 21)],   # wan1 .. wan20
            "input",
            *[f"input{i}" for i in range(1, 21)], # input1 .. input20
            "uplink", "upstream", "internet", "gateway",
        )
        try:
            items = await asyncio.to_thread(self._list_resource, "/interface")
            ifaces = self._normalize_items(items)
            matched = []
            for iface in ifaces:
                comment = str(iface.get("comment", "") or "").lower()
                name = iface.get("name", "")
                if name and any(kw in comment for kw in ISP_KEYWORDS):
                    matched.append(name)
            return matched
        except Exception:
            return []

    # ── Interface Traffic (RouterOS 6 API) ──
    async def get_interface_traffic(self, interface_name: str = "ether1", duration: int = 1):
        """
        ROS 6: Ambil rx-byte dan tx-byte dari interface stats.
        Digunakan untuk kalkulasi delta bps antara dua polling cycle.
        Return: {"rx-bytes": int, "tx-bytes": int, "name": str}
        (Bukan real-time bps — caller harus hitung delta sendiri)
        """
        try:
            def cb(api):
                resource = api.get_resource("/interface")
                items = resource.get(name=interface_name)
                return items
            items = await asyncio.to_thread(self._execute, cb)
            if items and isinstance(items, list):
                item = items[0]
                return {
                    "name":     interface_name,
                    "rx-bytes": int(item.get("rx-byte", 0) or 0),
                    "tx-bytes": int(item.get("tx-byte", 0) or 0),
                }
            return {}
        except Exception as e:
            logger.debug(f"get_interface_traffic ROS6 gagal untuk {interface_name}: {e}")
            return {}

    async def get_all_interface_stats(self):
        """
        ROS 6: Ambil stats interface fisik (rx-byte, tx-byte) + deteksi ISP interface.
        Semua dalam 1 koneksi ke MikroTik — efisien.

        Return: {
            'stats':          {iface_name: {rx-bytes: int, tx-bytes: int}},
            'isp_interfaces': [nama-nama interface ISP/WAN yang terdeteksi]
        }

        ISP detection menggunakan keyword di field 'comment'.
        Dilakukan dalam 1 loop — tidak perlu koneksi/call terpisah.
        """
        _SKIP_TYPES = {
            "bridge", "vlan", "pppoe-out", "pppoe-in", "l2tp", "pptp",
            "ovpn-client", "ovpn-server", "sstp-client", "sstp-server",
            "gre", "eoip", "eoipv6", "veth", "wireguard", "loopback",
            "6to4", "ipip", "ipip6",
        }
        _SKIP_PREFIXES = ("lo", "docker", "veth", "tun", "tap", "<")
        _ISP_KEYWORDS = (
            "isp", *[f"isp{i}" for i in range(1, 21)],
            "wan", *[f"wan{i}" for i in range(1, 21)],
            "input", *[f"input{i}" for i in range(1, 21)],
            "uplink", "upstream", "internet", "gateway",
        )
        try:
            items = await asyncio.to_thread(self._list_resource, "/interface")
            stats              = {}
            isp_ifaces         = []
            isp_comments: dict = {}   # {iface_name: original_comment}
            for item in items:
                name  = item.get("name", "")
                itype = item.get("type", "").lower()
                if not name:
                    continue
                # Deteksi ISP/WAN dari comment (satu loop, tidak perlu call terpisah)
                raw_comment = str(item.get("comment", "") or "")
                comment     = raw_comment.lower()
                if any(kw in comment for kw in _ISP_KEYWORDS):
                    isp_ifaces.append(name)
                    isp_comments[name] = raw_comment   # simpan comment asli (case-preserved)
                # Skip virtual/internal interfaces
                if itype in _SKIP_TYPES or name.lower().startswith(_SKIP_PREFIXES):
                    continue
                stats[name] = {
                    "rx-bytes": int(item.get("rx-byte", 0) or 0),
                    "tx-bytes": int(item.get("tx-byte", 0) or 0),
                }
            return {"stats": stats, "isp_interfaces": isp_ifaces, "isp_comments": isp_comments}
        except Exception as e:
            logger.debug(f"get_all_interface_stats ROS6 gagal: {e}")
            return {"stats": {}, "isp_interfaces": [], "isp_comments": {}}


    # ── IP Address List ──
    async def list_ip_addresses(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/address")
            return self._normalize_items(items)
        except Exception:
            return []

    # ── BGP ──
    async def list_bgp_peers(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/routing/bgp/peer")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_bgp_sessions(self):
        return []  # RouterOS 6 doesn't have separate sessions

    # ── OSPF ──
    async def list_ospf_neighbors(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/routing/ospf/neighbor")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_ospf_instances(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/routing/ospf/instance")
            return self._normalize_items(items)
        except Exception:
            return []

    # ── IP Routes ──
    async def list_ip_routes(self, limit: int = 200):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/route")
            return self._normalize_items(items)[:limit]
        except Exception:
            return []

    # ── Active Connections ──
    async def list_connections(self, limit: int = 500):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/firewall/connection")
            return self._normalize_items(items)[:limit]
        except Exception:
            return []

    # ── Firewall ──
    async def list_firewall_filter(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/firewall/filter")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_firewall_nat(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/firewall/nat")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_firewall_mangle(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/firewall/mangle")
            return self._normalize_items(items)
        except Exception:
            return []

    # ── Session Counters ──
    async def list_pppoe_active(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ppp/active")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_hotspot_active(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/hotspot/active")
            return self._normalize_items(items)
        except Exception:
            return []

    # ── Bulk Polling (ROS6 Optimization) ──
    def _get_polling_data_sync(self, fetch_system: bool):
        """Execute all polling API commands in a single persistent TCP connection."""
        pool = self._get_connection()
        try:
            api = pool.get_api()
            data = {}
            
            def safe_get(path):
                try:
                    return api.get_resource(path).get()
                except Exception as e:
                    return e

            ifaces = safe_get("/interface")
            data["ifaces"] = self._normalize_items(ifaces) if isinstance(ifaces, list) else ifaces
            
            # Cari nama interface ISP1
            isp1_name = ""
            if isinstance(ifaces, list):
                for iface in ifaces:
                    if not isinstance(iface, dict): continue
                    name = iface.get("name", "")
                    comment = str(iface.get("comment", "") or "").lower()
                    if "isp1" in name.lower() or "1" in comment:
                        isp1_name = name
                        break

            try:
                args = {"address": "8.8.8.8", "count": "3"}
                if isp1_name:
                    args["interface"] = isp1_name
                ping_res = api.get_resource("/").call("ping", args)
                data["ping"] = self._normalize_items(ping_res) if isinstance(ping_res, list) else ping_res
            except Exception as e:
                data["ping"] = e

            if fetch_system:
                sys = safe_get("/system/resource")
                data["sys"] = sys[0] if isinstance(sys, list) and sys else (sys if isinstance(sys, Exception) else {})
                
                health = safe_get("/system/health")
                if isinstance(health, list):
                    # Format standard kesehatan ROS6
                    result = {"voltage": 0, "cpu_temp": 0, "board_temp": 0, "power": 0, "fans": {}, "current": 0}
                    def _f(v):
                        try:
                            return float(str(v).replace('C', '').replace('V', '').replace('W', '').replace('RPM', '').replace('A', '').strip())
                        except:
                            return 0
                    for item in health:
                        name = item.get("name", "").lower()
                        value = item.get("value", "")
                        typ = item.get("type", "").upper()
                        if "voltage" in name:
                            if result["voltage"] == 0: result["voltage"] = _f(value)
                        elif "temperature" in name:
                            if "cpu" in name: result["cpu_temp"] = _f(value)
                            else: result["board_temp"] = _f(value)
                        elif typ == "W": result["power"] = _f(value)
                        elif typ == "RPM": result["fans"][name] = int(_f(value))
                        elif typ == "":
                            if "fan" in name: result["fans"][name] = int(_f(value))
                            elif "volt" in name:
                                if result["voltage"] == 0: result["voltage"] = _f(value)
                    data["health"] = result
                else:
                    data["health"] = health

                pppoe = safe_get("/ppp/active")
                data["pppoe"] = self._normalize_items(pppoe) if isinstance(pppoe, list) else pppoe

                hotspot = safe_get("/ip/hotspot/active")
                data["hotspot"] = self._normalize_items(hotspot) if isinstance(hotspot, list) else hotspot
                
            return data
        finally:
            try:
                pool.disconnect()
            except Exception:
                pass

    async def get_polling_data(self, fetch_system: bool):
        return await asyncio.to_thread(self._get_polling_data_sync, fetch_system)

    # ── Ping (ROS 6.x API Protocol) ──
    async def ping_host(self, address: str = "8.8.8.8", count: int = 4, interface: str = ""):
        """
        Melakukan ping dari router ke target address via command /ping.
        Mengembalikan list of dict response ping.
        """
        try:
            def cb(api):
                resource = api.get_resource("/")
                args = {"address": address, "count": str(count)}
                if interface:
                    args["interface"] = interface
                return resource.call("ping", args)
            
            items = await asyncio.to_thread(self._execute, cb)
            return self._normalize_items(items) if items else []
        except Exception as e:
            logger.debug(f"ping_host API Protocol gagal ke {address}: {e}")
            return []

# Backward compatibility alias
MikroTikRouterAPI = MikroTikLegacyAPI


# ═══════════════════════════════════════════════════════════
# Helper — extract hanya host dari ip_address (tanpa port)
# Digunakan untuk SNMP dan ICMP ping yang memerlukan plain IP
# ═══════════════════════════════════════════════════════════
def get_host_only(ip_address: str) -> str:
    """Ambil hanya bagian host dari 'host:port' format."""
    host, _ = parse_host_port(ip_address)
    return host


# ═══════════════════════════════════════════════════════════
# Discovery & Version Detection
# ═══════════════════════════════════════════════════════════
async def discover_device(device: dict) -> dict:
    """
    Deteksi otomatis mode API yang tepat untuk device ini.

    Urutan coba:
      1. REST API (port 443 HTTPS atau 80 HTTP) → mode=rest  (ROS 7.x)
      2. API Protocol (port 8728)               → mode=api   (ROS 6.x)

    Return dict:
      {
        "api_mode":      "rest" | "api" | "unknown",
        "version_major": 7 | 6 | 0,
        "ros_version":   "7.x.x" | "6.x.x" | "",
        "board_name":    str,
        "detected_at":   float (timestamp),
        "success":       bool,
      }

    Simpan hasil ke DB agar tidak re-discover setiap siklus 30 detik.
    Caller (polling) cukup re-discover jika `api_mode` belum ada di device,
    atau jika polling gagal berkali-kali dan mau coba mode lain.
    """
    import time
    raw_ip = device.get("ip_address", "")
    parsed_host, port_from_ip = parse_host_port(raw_ip)

    result = {
        "api_mode":      "unknown",
        "version_major": 0,
        "ros_version":   "",
        "board_name":    "",
        "detected_at":   time.time(),
        "success":       False,
    }

    # ── Coba REST API (ROS 7.x) ───────────────────────────────────────────────
    # Urutan port: custom port dari ip_address → 443 (HTTPS) → 80 (HTTP)
    rest_ports_ssl = []
    if port_from_ip is not None:
        rest_ports_ssl.append((port_from_ip, port_from_ip in (443, 8443)))
    rest_ports_ssl += [(443, True), (80, False)]

    for rest_port, use_ssl in rest_ports_ssl:
        try:
            rest_client = MikroTikRestAPI(
                host=parsed_host, username=device.get("api_username", "admin"),
                password=device.get("api_password", ""),
                port=rest_port, use_ssl=use_ssl,
            )
            # Override timeout menjadi pendek (5s) agar discovery cepat
            rest_client.timeout = 5
            test = await rest_client.test_connection()
            if test.get("success"):
                # Ambil versi ROS
                try:
                    sys_res = await asyncio.wait_for(
                        rest_client._async_req("GET", "system/resource"), timeout=5
                    )
                    ros_ver = sys_res.get("version", "") if isinstance(sys_res, dict) else ""
                    board   = sys_res.get("board-name", "") if isinstance(sys_res, dict) else ""
                except Exception:
                    ros_ver, board = "", ""

                ver_major = 7
                if ros_ver and ros_ver[0].isdigit():
                    try:
                        ver_major = int(ros_ver.split(".")[0])
                    except Exception:
                        pass

                result.update({
                    "api_mode":      "rest",
                    "version_major": ver_major,
                    "ros_version":   ros_ver,
                    "board_name":    board,
                    "success":       True,
                    "rest_port":     rest_port,
                    "use_https":     use_ssl,
                })
                logger.info(
                    f"Discovery [{device.get('name','?')}@{parsed_host}]: "
                    f"REST API OK port={rest_port} ssl={use_ssl} ROS={ros_ver}"
                )
                return result
        except Exception:
            pass

    # ── Coba API Protocol (ROS 6.x) ───────────────────────────────────────────
    api_port = port_from_ip if port_from_ip is not None else (device.get("api_port") or 8728)
    try:
        api_client = MikroTikRouterAPI(
            host=parsed_host,
            username=device.get("api_username", "admin"),
            password=device.get("api_password", ""),
            port=api_port,
            use_ssl=device.get("api_ssl", False),
            plaintext_login=device.get("api_plaintext_login", True),
        )
        test = await asyncio.wait_for(api_client.test_connection(), timeout=8)
        if test.get("success"):
            try:
                sys_res = await asyncio.wait_for(api_client.get_system_resource(), timeout=5)
                ros_ver = sys_res.get("version", "") if isinstance(sys_res, dict) else ""
                board   = sys_res.get("board-name", "") if isinstance(sys_res, dict) else ""
            except Exception:
                ros_ver, board = "", ""

            ver_major = 6
            if ros_ver and ros_ver[0].isdigit():
                try:
                    ver_major = int(ros_ver.split(".")[0])
                except Exception:
                    pass

            result.update({
                "api_mode":      "api",
                "version_major": ver_major,
                "ros_version":   ros_ver,
                "board_name":    board,
                "success":       True,
                "api_port":      api_port,
            })
            logger.info(
                f"Discovery [{device.get('name','?')}@{parsed_host}]: "
                f"API Protocol OK port={api_port} ROS={ros_ver}"
            )
            return result
    except Exception as e:
        logger.debug(f"Discovery API Protocol gagal [{parsed_host}]: {e}")

    logger.warning(
        f"Discovery [{device.get('name','?')}@{parsed_host}]: "
        f"Semua mode gagal — pastikan kredensial dan port benar"
    )
    return result


# ═══════════════════════════════════════════════════════════
# Factory function
# ═══════════════════════════════════════════════════════════
def get_api_client(device: dict) -> MikroTikBase:
    """
    Create the appropriate MikroTik API client based on device config.
    Mendukung ip_address dalam format 'host' atau 'host:port'.
    Jika ip_address mengandung port (host:port), port tersebut digunakan
    secara otomatis dan WWW Port / API Port field diabaikan.
    """
    mode = device.get("api_mode", "rest")
    raw_ip = device.get("ip_address", "")

    # Parse host:port dari ip_address
    parsed_host, port_from_ip = parse_host_port(raw_ip)

    if mode == "api":
        # RouterOS 6.x — API Protocol (MikroTikLegacyAPI)
        port = port_from_ip if port_from_ip is not None else (device.get("api_port") or 8728)
        logger.info(f"Creating MikroTikLegacyAPI client: host={parsed_host}, port={port}")
        return MikroTikLegacyAPI(
            host=parsed_host,
            username=device.get("api_username", "admin"),
            password=device.get("api_password", ""),
            port=port,
            use_ssl=device.get("api_ssl", False),
            plaintext_login=device.get("api_plaintext_login", True),
        )
    else:
        # RouterOS 7.x — REST API (MikroTikRestAPI)
        use_https = device.get("use_https", False)
        default_port = 443 if use_https else 80
        port = port_from_ip if port_from_ip is not None else (device.get("api_port") or default_port)
        logger.info(f"Creating MikroTikRestAPI client: host={parsed_host}, port={port}, https={use_https}")
        return MikroTikRestAPI(
            host=parsed_host,
            username=device.get("api_username", "admin"),
            password=device.get("api_password", ""),
            port=port,
            use_ssl=use_https,
        )
