import json
import urllib.request
import base64
from pymongo import MongoClient

def test():
    client = MongoClient("mongodb://nocsentinel:123Admin@localhost:27017/nocsentinel")
    db = client.nocsentinel
    
    dev = db.devices.find_one({"api_mode": "rest"})
    if not dev:
        print("No ROS7 REST device found")
        return
        
    print(f"Testing device: {dev.get('name')} IP: {dev.get('ip_address')}")
    url = f"http://{dev['ip_address'].split(':')[0]}/rest/ping"
    print(f"POST {url}")
    
    auth_str = f"{dev.get('api_username', 'admin')}:{dev.get('api_password', '')}"
    b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    
    import ssl
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

test()
