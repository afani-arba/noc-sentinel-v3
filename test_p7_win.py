import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from core.db import db
from mikrotik_api import get_api_client

async def test():
    # Attempt to connect to local mongo
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
    mt = get_api_client(dev)
    
    # Let's find an iface
    ifaces = await mt.list_interfaces()
    isp = ""
    for i in ifaces:
        if "1" in i.get("comment", ""):
            isp = i["name"]
            break
            
    print("ISP Interface:", isp)
    
    print("Testing ping with interface...")
    res = await mt.ping_host("8.8.8.8", count=3, interface=isp)
    print("Ping Output:", res)

asyncio.run(test())
