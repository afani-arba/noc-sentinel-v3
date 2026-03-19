import asyncio
import os
import sys

# point to modified code instead of system code
sys.path.insert(0, "/mnt/e/noc-sentinel-v3/backend")

from pymongo import MongoClient
import httpx

async def test():
    client = MongoClient("mongodb://nocsentinel:nocsentinel123%21@localhost:27017/nocsentinel")
    db = client.nocsentinel
    
    # Find reachable ROS 7 REST device
    dev = db.devices.find_one({
        "api_mode": "rest", 
        "ros_version": {"$regex": "v7"}, 
        "status": "online"
    })
    
    if not dev:
        print("No online ROS 7 REST devices found.")
        dev = db.devices.find_one({"api_mode": "rest"})
        
    print(f"Testing device: {dev.get('name')} IP: {dev.get('ip_address')} Version: {dev.get('ros_version')}")
    
    # 1. Test via HTTPX directly to see payload error
    url = f"http://{dev['ip_address'].split(':')[0]}/rest/ping"
    print(f"\nPOST {url}")
    
    auth_tup = (dev.get('api_username', 'admin'), dev.get('api_password', ''))
    
    import base64
    auth_str = f"{dev.get('api_username', 'admin')}:{dev.get('api_password', '')}"
    b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers = {"Authorization": f"Basic {b64_auth}"}

    payload = {"address": "8.8.8.8", "count": "3"}
    print("Payload:", payload)
    
    try:
        async with httpx.AsyncClient(verify=False, timeout=10.0) as hc:
            resp = await hc.post(url, json=payload, auth=auth_tup)
            print("Status:", resp.status_code)
            print("Response:", resp.text)
    except Exception as e:
        print("HTTPX Error:", e)

    # 2. Test via the wrapper
    print("\n--- Testing wrapper ---")
    from mikrotik_api import get_api_client
    mt = get_api_client(dev)
    try:
        res = await mt.ping_host("8.8.8.8", count=3)
        print("Wrapper Ping Output:", res)
    except Exception as e:
        print("Wrapper Error:", type(e), e)

asyncio.run(test())
