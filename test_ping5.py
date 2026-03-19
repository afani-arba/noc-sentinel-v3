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
        
    dev = await db.devices.find_one({"api_mode": "rest", "ros_version": {"$regex": "v7"}})
    if not dev:
        print("No ROS7 REST device found")
        dev = await db.devices.find_one({"api_mode": "rest"})
        
    if not dev:
        print("No REST devices found")
        return
        
    print(f"Testing device: {dev.get('name')} IP: {dev.get('ip_address')} Version: {dev.get('ros_version')}")
    
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
        print("Error pinging tool:", type(e), e)
        if hasattr(e, 'read'):
            print("HTTP Body:", e.read().decode('utf-8'))
            
    # Try POST /rest/command/ping
    url = f"http://{dev['ip_address'].split(':')[0]}/rest/command/ping"
    print(f"\nPOST {url}")
    req = urllib.request.Request(url, data=payload.encode('utf-8'), method="POST")
    req.add_header("Authorization", f"Basic {b64_auth}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = resp.read()
            print("Status:", resp.status)
            print("Response text:", data.decode('utf-8'))
    except Exception as e:
        print("Error pinging tool:", type(e), e)
        if hasattr(e, 'read'):
            print("HTTP Body:", e.read().decode('utf-8'))


asyncio.run(test())
