import os
import sys
import asyncio
from dotenv import load_dotenv

import mikrotik_api
import core.db

async def test_ping():
    db = core.db.init_db()
    devices = await db.devices.find({}).to_list(10)
    for dev in devices:
        ip = dev.get("ip_address")
        mode = dev.get("api_mode", "rest")
        print(f"Testing {ip} (Mode: {mode})")
        
        try:
            client = mikrotik_api.get_api_client(dev)
            
            if hasattr(client, "_async_req"):
                # REST API
                print("Trying REST POST tool/ping...")
                res = await client._async_req("POST", "tool/ping", {"address": "8.8.8.8", "count": 3})
                print("REST Ping Response:")
                print(res)
            else:
                # Legacy API
                print("Trying RouterOS 6 API /ping...")
                def cb(api):
                    ping_res = api.get_resource("/").call("ping", {"address": "8.8.8.8", "count": "3"})
                    return ping_res
                
                res = await asyncio.to_thread(client._execute, cb)
                print("Legacy Ping Response:")
                print(res)
                
        except Exception as e:
            print(f"Error {ip}: {e}")
            
    core.db.close_db()

if __name__ == "__main__":
    asyncio.run(test_ping())
