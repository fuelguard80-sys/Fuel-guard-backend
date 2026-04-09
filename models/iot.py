from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime


class DeviceType(str, Enum):
    ESP32        = "esp32"
    FLOW_METER   = "flow_meter"
    CAMERA       = "camera"
    GATEWAY      = "gateway"


class DeviceStatus(str, Enum):
    ONLINE       = "online"
    OFFLINE      = "offline"
    UPDATING     = "updating"
    ERROR        = "error"


class DeviceRegister(BaseModel):
    device_id: str = Field(description="Hardware device unique ID (MAC address or UUID)")
    device_type: DeviceType
    nozzle_id: Optional[str] = None
    station_id: Optional[str] = None
    firmware_version: str
    ip_address: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DeviceResponse(BaseModel):
    id: str
    device_id: str
    device_type: DeviceType
    nozzle_id: Optional[str] = None
    station_id: Optional[str] = None
    firmware_version: str
    ip_address: Optional[str] = None
    status: DeviceStatus
    last_ping: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class DevicePing(BaseModel):
    device_id: str
    firmware_version: Optional[str] = None
    ip_address: Optional[str] = None


class TelemetryPayload(BaseModel):
    device_id: str
    nozzle_id: Optional[str] = None
    flow_rate: Optional[float] = None
    total_dispensed: Optional[float] = None
    tamper_detected: Optional[bool] = None
    temperature: Optional[float] = None
    signal_strength: Optional[int] = None
    timestamp: Optional[datetime] = None
    extras: Optional[Dict[str, Any]] = None


class CameraCapture(BaseModel):
    reason: str = "manual"  # manual | tamper | session_start | session_end


class FlowCalibration(BaseModel):
    calibration_factor: float = Field(gt=0, description="Pulses per litre")
    offset: float = 0.0


class FirmwareUpload(BaseModel):
    version: str
    release_notes: Optional[str] = None
    is_mandatory: bool = False


class FirmwareUpdateRequest(BaseModel):
    firmware_version: str
    force: bool = False


class FirmwareStatusResponse(BaseModel):
    device_id: str
    current_version: str
    target_version: Optional[str] = None
    update_status: str  # idle | downloading | installing | complete | failed
    progress_percent: Optional[int] = None
    last_updated: Optional[datetime] = None
