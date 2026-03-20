import asyncio
import logging
import threading
import socket
from datetime import datetime, timezone
import uuid

from pyrad.server import Server
from pyrad.dictionary import Dictionary
from pyrad.packet import AccessAccept, AccessReject, AccountingResponse

logger = logging.getLogger(__name__)

# To communicate with async db from sync thread
db_loop = None
db_pool = None

class ARBARadiusServer(Server):
    def __init__(self, dict_path, mikrotik_dict_path):
        super().__init__(dict=Dictionary(dict_path, mikrotik_dict_path))
        self.auth_port = 1812
        self.acct_port = 1813
        # Dynamically load clients from DB? For now, we accept all and rely on standard secrets.
        # But wait, pyrad requires pre-populating hosts.
        # We will populate it in a loop periodically, or just inject dynamically if possible.
        # To avoid blocking, we can rely on a wildcard listener or just read from DB at startup.
        
    def _run_async(self, coro):
        """Run an async coroutine from the sync thread."""
        if db_loop and not db_loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(coro, db_loop)
            return future.result()
        return None
        
    def HandleAuthPacket(self, pkt):
        logger.info(f"Received RADIUS Auth Request from {pkt.source[0]}")
        # Parse username and password
        username = pkt.get(1) # User-Name
        password = pkt.get(2) # User-Password
        
        reply = self.CreateReplyPacket(pkt, **{'Code': AccessReject})
        
        if not username or not password:
            self.SendReplyPacket(pkt.fd, reply)
            return

        uname = username[0].decode('utf-8')
        try:
            # Requires PAP decryption
            pwd = self.DecryptPassword(password[0])
            pwd_str = pwd.decode('utf-8').rstrip('\x00')
        except Exception as e:
            logger.warning(f"Failed to decrypt PAP password for {uname}: {e}")
            self.SendReplyPacket(pkt.fd, reply)
            return

        # Check DB
        async def verify_user():
            if not db_pool: return None
            return await db_pool.hotspot_vouchers.find_one({"username": uname})
            
        voucher = self._run_async(verify_user())
        
        if voucher:
            # Check if expired or correct password
            if password == b'': # MAC Auth might send empty password depending on config
                pass
            if voucher.get("password") == pwd_str:
                # Password correct, now check if active or expired
                status = voucher.get("status", "new")
                if status == "expired":
                    # Tell Mikrotik session is expired
                    reply = self.CreateReplyPacket(pkt, **{'Code': AccessReject})
                    reply.AddAttribute('Reply-Message', b'Voucher expired')
                else:
                    reply = self.CreateReplyPacket(pkt, **{'Code': AccessAccept})
                    # Add Mikrotik Rate Limit if profile has one defined in DB
                    rate = voucher.get("profile_rate_limit")
                    if rate:
                        reply.AddAttribute('MikroTik-Rate-Limit', rate.encode('utf-8'))
            else:
                reply.AddAttribute('Reply-Message', b'Invalid password')
        else:
            reply.AddAttribute('Reply-Message', b'User not found')

        self.SendReplyPacket(pkt.fd, reply)

    def HandleAcctPacket(self, pkt):
        logger.info(f"Received RADIUS Acct Request from {pkt.source[0]}")
        
        status_type = pkt.get(40) # Acct-Status-Type
        username = pkt.get(1)     # User-Name
        
        reply = self.CreateReplyPacket(pkt, **{'Code': AccountingResponse})
        self.SendReplyPacket(pkt.fd, reply)
        
        if not status_type or not username:
            return
            
        stype = status_type[0]
        uname = username[0].decode('utf-8')
        
        # 1 = Start, 2 = Stop, 3 = Interim-Update
        async def process_acct():
            if not db_pool: return
            
            voucher = await db_pool.hotspot_vouchers.find_one({"username": uname})
            if not voucher: return
            
            now = datetime.now(timezone.utc).isoformat()
            
            if stype == 1: # Start
                if voucher.get("status") == "new":
                    # Mark as activated and record sale!
                    await db_pool.hotspot_vouchers.update_one(
                        {"_id": voucher["_id"]},
                        {"$set": {
                            "status": "active",
                            "activated_at": now
                        }}
                    )
                    
                    # Create Sales Invoice purely for record keeping
                    await db_pool.hotspot_sales.insert_one({
                        "id": str(uuid.uuid4()),
                        "voucher_id": str(voucher.get("_id")),
                        "username": uname,
                        "price": float(voucher.get("price", 0)),
                        "created_at": now,
                        "device_ip": pkt.source[0]
                    })
                    logger.info(f"Voucher {uname} logic ACCT-START applied - Sale Recorded!")
                    
        self._run_async(process_acct())

_server_thread = None

def start_radius_server(loop, _db):
    global db_loop, db_pool, _server_thread
    db_loop = loop
    db_pool = _db
    
    try:
        import pyrad.dictionary
        import os
    except ImportError:
        logger.error("pyrad not installed, RADIUS will not start")
        return
        
    try:
        # We need standard dictionary + mikrotik.
        # Create a proxy for default pyrad dictionaries
        import site
        # Simplest way: use pyrad default dictionary and our custom mikrotik one.
        dict_path = os.path.join(os.path.dirname(pyrad.__file__), "dict", "dictionary")
        mt_dict = os.path.join(os.path.dirname(__file__), "dictionary.mikrotik")
        
        server = ARBARadiusServer(dict_path, mt_dict)
        
        # We must load all possible device IPs and their secrets to accept packets.
        # Since DB loading is async, we'll do an initial synchronous load or just a wildcard 
        # But pyrad expects predefined secrets:
        server.hosts["127.0.0.1"] = server.CreateClient("127.0.0.1", b"secret", "NOC-Sentinel-Local")
        # In a real scenario, fetch devices from _db loop synchronously here or allow all bypass.
        # For simplicity, we can dynamically add hosts if we bypass pyrad's internal check.
        # But let's add a default for local tests.
        
        class MockClient:
            def __init__(self, secret):
                self.secret = secret

        # Monkey patch pyrad to accept any client with a master secret or use device secrets
        # Real-world: read all active devices from DB.
        
        _server_thread = threading.Thread(target=server.Run, daemon=True)
        _server_thread.start()
        logger.info("RADIUS Server started on UDP 1812/1813")
        
    except Exception as e:
        logger.error(f"Failed to start RADIUS server: {e}")
