"""
Unified MikroTik API client supporting both:
  - RouterOS 6.x: MikroTik API protocol (port 8728/8729)
  - RouterOS 7.x: REST API (port 443/80)
Both implementations share the same interface.
"""
import requests
import asyncio
import logging
import urllib3
import routeros_api

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


# ── Base interface ──
class MikroTikBase:
    async def test_connection(self): raise NotImplementedError
    async def list_pppoe_secrets(self): raise NotImplementedError
    async def create_pppoe_secret(self, data): raise NotImplementedError
    async def update_pppoe_secret(self, mt_id, data): raise NotImplementedError
    async def delete_pppoe_secret(self, mt_id): raise NotImplementedError
    async def list_pppoe_active(self): raise NotImplementedError
    async def list_hotspot_users(self): raise NotImplementedError
    async def create_hotspot_user(self, data): raise NotImplementedError
    async def update_hotspot_user(self, mt_id, data): raise NotImplementedError
    async def delete_hotspot_user(self, mt_id): raise NotImplementedError
    async def list_hotspot_active(self): raise NotImplementedError


# ═══════════════════════════════════════════════════════════
# RouterOS 7+ REST API
# ═══════════════════════════════════════════════════════════
class MikroTikRestAPI(MikroTikBase):
    def __init__(self, host, username, password, port=443, use_ssl=True):
        scheme = "https" if use_ssl else "http"
        self.base_url = f"{scheme}://{host}:{port}/rest"
        self.auth = (username, password)
        self.verify = False
        self.timeout = 10

    def _request(self, method, path, data=None):
        url = f"{self.base_url}/{path}"
        logger.info(f"REST API request: {method} {url}")
        try:
            resp = requests.request(method, url, auth=self.auth, json=data,
                                    verify=self.verify, timeout=self.timeout)
            logger.info(f"REST API response: {resp.status_code}")
            if resp.status_code == 401:
                raise Exception("Authentication failed - check API username/password")
            if resp.status_code == 400:
                detail = resp.json() if resp.content else {}
                raise Exception(f"Bad request: {detail.get('detail', detail.get('message', resp.text))}")
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL Error: {e}")
            raise Exception(f"SSL Error - coba nonaktifkan SSL atau gunakan port HTTP. Detail: {e}")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection Error: {e}")
            raise Exception(f"Cannot connect to REST API at {url} - pastikan www atau www-ssl service aktif di MikroTik")
        except requests.exceptions.Timeout:
            raise Exception("Connection timed out - periksa firewall dan pastikan port terbuka")
        except Exception as e:
            if any(k in str(e) for k in ["Authentication", "Bad request", "Cannot connect", "timed out", "SSL Error"]):
                raise
            raise Exception(f"REST API error: {e}")

    async def _async_req(self, method, path, data=None):
        return await asyncio.to_thread(self._request, method, path, data)

    async def test_connection(self):
        try:
            r = await self._async_req("GET", "system/identity")
            return {"success": True, "identity": r.get("name", ""), "mode": "REST API (RouterOS 7+)"}
        except Exception as e:
            return {"success": False, "error": str(e), "mode": "REST API (RouterOS 7+)"}

    async def list_pppoe_secrets(self):
        return await self._async_req("GET", "ppp/secret")

    async def create_pppoe_secret(self, data):
        return await self._async_req("PUT", "ppp/secret", data)

    async def update_pppoe_secret(self, mt_id, data):
        return await self._async_req("PATCH", f"ppp/secret/{mt_id}", data)

    async def delete_pppoe_secret(self, mt_id):
        return await self._async_req("DELETE", f"ppp/secret/{mt_id}")

    async def list_pppoe_active(self):
        return await self._async_req("GET", "ppp/active")

    async def list_hotspot_users(self):
        return await self._async_req("GET", "ip/hotspot/user")

    async def create_hotspot_user(self, data):
        return await self._async_req("PUT", "ip/hotspot/user", data)

    async def update_hotspot_user(self, mt_id, data):
        return await self._async_req("PATCH", f"ip/hotspot/user/{mt_id}", data)

    async def delete_hotspot_user(self, mt_id):
        return await self._async_req("DELETE", f"ip/hotspot/user/{mt_id}")

    async def list_hotspot_active(self):
        return await self._async_req("GET", "ip/hotspot/active")


# ═══════════════════════════════════════════════════════════
# RouterOS 6.x+ MikroTik API Protocol (port 8728/8729)
# ═══════════════════════════════════════════════════════════
class MikroTikRouterAPI(MikroTikBase):
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


# ═══════════════════════════════════════════════════════════
# Factory function
# ═══════════════════════════════════════════════════════════
def get_api_client(device: dict) -> MikroTikBase:
    """Create the appropriate MikroTik API client based on device config."""
    mode = device.get("api_mode", "rest")

    if mode == "api":
        # RouterOS 6+ API protocol
        # Gunakan api_port jika ada, kalau tidak gunakan default 8728
        port = device.get("api_port") or 8728
        return MikroTikRouterAPI(
            host=device["ip_address"],
            username=device.get("api_username", "admin"),
            password=device.get("api_password", ""),
            port=port,
            use_ssl=device.get("api_ssl", False),
            plaintext_login=device.get("api_plaintext_login", True),
        )
    else:
        # RouterOS 7+ REST API
        # Prioritas: ssl_port > api_port > default 443
        port = device.get("ssl_port") or device.get("api_port") or 443
        
        # Auto-detect SSL: jika api_ssl tidak di-set explicit, gunakan logic berdasarkan port
        # Port 443 biasanya HTTPS, port lain (80, custom) biasanya HTTP
        api_ssl_value = device.get("api_ssl")
        if api_ssl_value is None:
            # Auto-detect: port 443 = https, lainnya = http
            use_ssl = (port == 443)
        else:
            use_ssl = api_ssl_value
        
        return MikroTikRestAPI(
            host=device["ip_address"],
            username=device.get("api_username", "admin"),
            password=device.get("api_password", ""),
            port=port,
            use_ssl=use_ssl,
        )
