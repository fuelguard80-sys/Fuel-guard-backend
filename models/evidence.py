from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class EvidenceCreate(BaseModel):
    transaction_id: str
    nozzle_id: str
    session_id: Optional[str] = None
    capture_trigger: str = "auto"  # auto | manual | tamper


class EvidenceResponse(BaseModel):
    id: str
    transaction_id: str
    nozzle_id: str
    session_id: Optional[str] = None
    image_url: str
    thumbnail_url: Optional[str] = None
    file_size_kb: Optional[float] = None
    capture_trigger: str
    metadata: Optional[dict] = None
    watermark_text: Optional[str] = None
    delete_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class EvidenceListResponse(BaseModel):
    total: int
    items: list[EvidenceResponse]
