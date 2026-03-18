#!/usr/bin/env python3
import os
from pymongo import MongoClient

def main():
    env_file = "/etc/noc-sentinel/peering-eye.env"
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    if k == "MONGO_URL": os.environ["MONGO_URL"] = v
                    if k == "MONGO_DB": os.environ["MONGO_DB"] = v

    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017/noc_sentinel")
    db_name = os.environ.get("MONGO_DB", "noc_sentinel")

    try:
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        db = client[db_name]
        db.peering_eye_stats.drop()
        print("\n🔥 SUKSES: 162 TB Traffic (dan semua history) berhasil dihapus! 🔥")
        print("Silakan Refresh Dashboard Sentinel Peering-Eye.\n")
    except Exception as e:
        print(f"\n[ERROR] Gagal menghapus database: {e}\n")

if __name__ == "__main__":
    main()
