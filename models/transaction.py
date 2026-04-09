from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime


class PaymentMethod(str, Enum):
    CASH    = "cash"
    CARD    = "card"
    WALLET  = "wallet"
    QR_PAY  = "qr_pay"


class TransactionStatus(str, Enum):
    PENDING   = "pending"
    COMPLETED = "completed"
    FAILED    = "failed"
    REFUNDED  = "refunded"


class TransactionCreate(BaseModel):
    session_id: str
    nozzle_id: str
    user_id: str
    vehicle_id: Optional[str] = None
    fuel_type: str
    litres_dispensed: float = Field(gt=0)
    price_per_litre: float = Field(gt=0)
    payment_method: PaymentMethod = PaymentMethod.CASH
    employee_id: Optional[str] = None


class TransactionResponse(BaseModel):
    id: str
    session_id: str
    nozzle_id: str
    user_id: str
    vehicle_id: Optional[str] = None
    fuel_type: str
    litres_dispensed: float
    price_per_litre: float
    total_amount: float
    payment_method: PaymentMethod
    status: TransactionStatus
    employee_id: Optional[str] = None
    station_id: Optional[str] = None
    receipt_url: Optional[str] = None
    evidence_url: Optional[str] = None
    is_flagged: bool = False
    created_at: Optional[datetime] = None


class PriceUpdate(BaseModel):
    price_per_litre: float = Field(gt=0)
    reason: Optional[str] = None


class CurrentPrice(BaseModel):
    fuel_type: str
    price_per_litre: float
    station_id: Optional[str] = None
    effective_from: Optional[datetime] = None


class PriceUpdateRequest(BaseModel):
    fuel_type: str
    price_per_litre: float = Field(gt=0)
    station_id: Optional[str] = None
