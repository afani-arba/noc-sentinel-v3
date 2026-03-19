import asyncio
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, "/opt/noc-sentinel-v3/backend")
load_dotenv("/opt/noc-sentinel-v3/backend/.env")

from core.db import init_db

async def test():
    db = init_db()
    # Test connection
    try:
        await db.client.nocsentinel.command("ping")
    except Exception as e:
        print("MongoDB error:", e)
        return
        
    dev = await db.devices.find_one({"api_mode": "rest"})
    if not dev:
        print("No ROS7 REST device found")
        return
        
    print(f"Testing device: {dev.get('name')} IP: {dev.get('ip_address')}")
    
    # Test the API wrapper function directly to see its parsing error
    from mikrotik_api import get_api_client
    mt = get_api_client(dev)
    print("API Wrapper:", mt)
    
    import logging
    logging.basicConfig(level=logging.DEBUG)
    
    res = await mt.ping_host("8.8.8.8", count=3)
    print("Wrapper Output:", res)
    
    # Test HTTP directly
    import urllib.request
    import base64
    import json
    import ssl
    
    url = f"http://{dev['ip_address'].split(':')[0]}/rest/ping"
    print(f"\nPOST {url}")
    
    auth_str = f"{dev.get('api_username', 'admin')}:{dev.get('api_password', '')}"
    b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    payload = json.dumps({"address": "8.8.8.8", "count": "3"})
    print("Payload:", payload)
    
    req = urllib.request.Request(url, data=payload.encode('utf-8'), method="POST")
    req.add_header("Authorization", f"Basic {b64_auth}")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = resp.read()
            print("Status:", resp.status)
            print("Response text:", data.decode('utf-8'))
    except Exception as e:
        print("Error pinging tool:", e)
        if hasattr(e, 'read'):
            print("HTTP Body:", e.read().decode('utf-8'))

asyncio.run(test())
