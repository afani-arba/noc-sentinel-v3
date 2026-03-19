import asyncio
from core.db import db
from mikrotik_api import get_api_client

async def test():
    await db.client.noc_sentinel.command("ping")
    cursor = db.devices.find({"api_mode": "rest"})
    async for dev in cursor:
        print("Dev:", dev["name"], dev["ip_address"])
        mt = get_api_client(dev)
        res = await mt.ping_host("8.8.8.8", count=2)
        print("RAW PING:", res)
        break

asyncio.run(test())
