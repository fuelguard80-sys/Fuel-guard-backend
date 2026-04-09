from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class PriceRecord(BaseModel):
    id: str
    station_id: str
    fuel_type: str
    price_per_litre: float
    updated_by: Optional[str] = None
    effective_from: datetime
    created_at: Optional[datetime] = None


class PriceAlertCreate(BaseModel):
    station_id: str
    fuel_type: str
    target_price: float = Field(gt=0, description="Alert when price drops to or below this value")


class PriceAlertResponse(BaseModel):
    id: str
    user_id: str
    station_id: str
    fuel_type: str
    target_price: float
    is_active: bool = True
    created_at: Optional[datetime] = None


class PriceCompareResponse(BaseModel):
    station_id: str
    station_name: str
    fuel_type: str
    price_per_litre: float
    distance_km: Optional[float] = None
    last_updated: Optional[datetime] = None


class CheapestFuelRequest(BaseModel):
    latitude: float
    longitude: float
    fuel_type: str
    radius_km: float = 20.0
