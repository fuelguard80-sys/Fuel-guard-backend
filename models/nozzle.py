from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime


class FuelType(str, Enum):
    PETROL    = "petrol"
    DIESEL    = "diesel"
    PREMIUM   = "premium"
    CNG       = "cng"
    LPG       = "lpg"


class NozzleStatus(str, Enum):
    IDLE        = "idle"
    DISPENSING  = "dispensing"
    OFFLINE     = "offline"
    TAMPERED    = "tampered"
    MAINTENANCE = "maintenance"


class NozzleCreate(BaseModel):
    name: str
    station_id: str
    fuel_type: FuelType
    # BLE hardware pairing — required at registration
    ble_uuid: str = Field(description="Bluetooth Low Energy UUID of the hardware device")
    ble_device_name: str = Field(description="BLE advertised device name (as seen during scan)")
    hardware_serial: str = Field(description="Physical serial number printed on the device")
    flow_meter_model: Optional[str] = None
    max_flow_rate: float = Field(default=60.0, description="Max flow rate in litres/min")


class NozzleUpdate(BaseModel):
    name: Optional[str] = None
    fuel_type: Optional[FuelType] = None
    ble_device_name: Optional[str] = None
    flow_meter_model: Optional[str] = None
    max_flow_rate: Optional[float] = None
    status: Optional[NozzleStatus] = None


class NozzleResponse(BaseModel):
    id: str
    name: str
    station_id: str
    fuel_type: FuelType
    ble_uuid: str
    ble_device_name: str
    hardware_serial: str
    flow_meter_model: Optional[str] = None
    max_flow_rate: float
    status: NozzleStatus
    is_active: bool
    tamper_detected: bool
    current_flow_rate: Optional[float] = None
    total_litres_today: float = 0.0
    last_seen: Optional[datetime] = None
    created_at: Optional[datetime] = None


class FlowReading(BaseModel):
    nozzle_id: str
    flow_rate: float = Field(description="Current flow rate in L/min")
    total_dispensed: float = Field(description="Total litres dispensed in current session")
    timestamp: Optional[datetime] = None


class TamperAlert(BaseModel):
    nozzle_id: str
    alert_type: str = Field(description="e.g. vibration, magnetic, cover_open")
    description: Optional[str] = None
    timestamp: Optional[datetime] = None


class TamperAlertResolve(BaseModel):
    resolution_note: str
