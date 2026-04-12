from pydantic import BaseModel
from typing import Optional
from enum import Enum
from datetime import datetime


class SessionStatus(str, Enum):
    PENDING   = "pending"
    ACTIVE    = "active"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class QRGenerateRequest(BaseModel):
    nozzle_id: str
    expires_in_seconds: int = 300


class QRGenerateResponse(BaseModel):
    session_id: str
    nozzle_id: str
    qr_data: str
    qr_image_base64: str
    expires_at: datetime


class QRScanRequest(BaseModel):
    qr_data: str
    user_id: Optional[str] = None


class SessionLinkRequest(BaseModel):
    user_id: str


class SessionResponse(BaseModel):
    id: str
    nozzle_id: str
    user_id: Optional[str] = None
    status: SessionStatus
    qr_data: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    total_litres: float = 0.0
    total_amount: float = 0.0
    transaction_id: Optional[str] = None


class SessionCloseRequest(BaseModel):
    reason: Optional[str] = "manual"


class DeviceSessionRequest(BaseModel):
    """Used when the app initiates a session directly from the ESP32 device
    (WiFi QR flow) rather than scanning a backend-generated QR code."""
    nozzle_id: str
