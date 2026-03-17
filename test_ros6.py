import asyncio
import sys
import os
from dotenv import load_dotenv

sys.path.append("/opt/noc-sentinel-v3/backend")
load_dotenv("/opt/noc-sentinel-v3/backend/.env")

from core.polling import poll_single_device
from core.db import init_db, close_db
from motor.motor_asyncio import AsyncIOMotorClient

async def test_ros6_device():
    init_db()
    
    from core.db import get_db
    db = get_db()
    
    # Find a ROS 6 device
    device = await db.devices.find_one({"api_mode": "api"})
    if not device:
        print("No ROS 6 device found")
        close_db()
        return

    print(f"Testing ROS 6 device: {device.get('name')} IP: {device.get('ip_address')}")
    
    try:
        start_t = asyncio.get_running_loop().time()
        res = await poll_single_device(device)
        end_t = asyncio.get_running_loop().time()
        print(f"Polling Exec Time: {end_t - start_t:.2f}s")
        print(f"Polling Result reachability: {res.get('reachable')}")
        if not res.get('reachable'):
            print(f"Exception/Reason for offline: {res.get('error', 'Unknown')}")
            if "ifaces_raw" in res:
                print(f"ifaces raw: {res.get('ifaces_raw')}")
    except Exception as e:
        import traceback
        traceback.print_exc()

    close_db()

if __name__ == "__main__":
    asyncio.run(test_ros6_device())
