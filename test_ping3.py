import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, "/opt/noc-sentinel-v3/backend")

from core.db import db

async def test():
    # Attempt to connect using the app's motor client
    try:
        await db.client.noc_sentinel.command("ping")
    except Exception as e:
        print("Mongo failed:", e)
        return
        
    dev = await db.devices.find_one({"api_mode": "rest"})
    if not dev:
        print("No rest devices")
        return
        
    print(f"Testing device: {dev.get('name')} IP: {dev.get('ip_address')}")
    
    # Test ping format manually
    import urllib.request
    import base64
    import json
    import ssl
    
    url = f"http://{dev['ip_address'].split(':')[0]}/rest/ping"
    print(f"POST {url}")
    
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
        print("Error pinging:", e)
        if hasattr(e, 'read'):
            print("Error body:", e.read().decode('utf-8'))

asyncio.run(test())
