import asyncio
import httpx
from pymongo import MongoClient

async def test():
    client = MongoClient("mongodb://localhost:27017/")
    db = client.noc_sentinel
    
    # Find a ROS 7 device
    dev = db.devices.find_one({"api_mode": "rest"})
    if not dev:
        print("No REST devices found")
        return
        
    print(f"Testing device: {dev.get('name')} IP: {dev.get('ip_address')}")
    
    url = f"http://{dev['ip_address'].split(':')[0]}/rest/tool/ping"
    auth = (dev.get("api_username", "admin"), dev.get("api_password", ""))
    
    print(f"POST {url}")
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as hc:
            resp = await hc.post(url, json={"address": "8.8.8.8", "count": 3}, auth=auth)
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test())
