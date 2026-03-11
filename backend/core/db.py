"""
Database connection singleton for NOC-Sentinel backend.
"""
import os
from motor.motor_asyncio import AsyncIOMotorClient

_client = None
_db = None


def get_client() -> AsyncIOMotorClient:
    return _client


def get_db():
    return _db


def init_db():
    global _client, _db
    # Support both MONGO_URI (new) and MONGO_URL (legacy)
    mongo_url = os.environ.get("MONGO_URI") or os.environ.get("MONGO_URL")
    if not mongo_url:
        raise RuntimeError("MONGO_URI (or MONGO_URL) environment variable is not set. Check your .env file.")
    # Support both MONGO_DB_NAME (new) and DB_NAME (legacy)
    db_name = os.environ.get("MONGO_DB_NAME") or os.environ.get("DB_NAME", "nocsentinel")
    _client = AsyncIOMotorClient(mongo_url)
    _db = _client[db_name]
    return _db


def close_db():
    global _client
    if _client:
        _client.close()
