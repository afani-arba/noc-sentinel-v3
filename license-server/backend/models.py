from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from uuid import uuid4

class ProductCreate(BaseModel):
    name: str = Field(..., title="Product Name")
    type: str = Field(..., description="monthly, yearly, or lifetime")
    duration_months: int = 1
    price: int = 0
    description: Optional[str] = None

class LicenseCreate(BaseModel):
    product_id: str
    customer_name: str
    max_devices: int = 1
    notes: Optional[str] = None

class VerifyRequest(BaseModel):
    license_key: str
    hardware_id: str
    ip_address: Optional[str] = ""

class LogEntry(BaseModel):
    id: str
    license_key: str
    hardware_id: str
    ip_address: str
    status: str
    timestamp: str
