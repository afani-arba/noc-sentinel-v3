import os
import sys
import asyncio
from dotenv import load_dotenv

# Set correct paths for imports
base_dir = "/opt/noc-sentinel-v3/backend"
sys.path.append(base_dir)
os.chdir(base_dir)

load_dotenv(os.path.join(base_dir, ".env"))

import core.db
from core.polling import poll_single_device

async def test_poll():
    # Initialize DB properly using the app's own mechanism
    db = core.db.init_db()
    
    device = await db.devices.find_one({})
    if not device:
        print("Tidak ada device")
        return
        
    print(f"Testing device: {device.get('name')} IP: {device.get('ip_address')}")
    
    try:
        res = await asyncio.wait_for(poll_single_device(device), timeout=15)
        print(f"Result API reachable: {res.get('reachable')}")
        print("Done!")
    except Exception as e:
        print(f"Exception di luar poll_single_device: {e.__class__.__name__} - {e}")
        
    core.db.close_db()

if __name__ == "__main__":
    asyncio.run(test_poll())
