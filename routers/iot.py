from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

import cloudinary
import cloudinary.uploader

from core.config import settings
from core.dependencies import require_admin
from core.firebase import Collections, ensure_utc, get_db
from models.iot import (
    CameraCapture,
    DevicePing,
    DeviceRegister,
    DeviceResponse,
    FirmwareStatusResponse,
    FirmwareUpdateRequest,
    FlowCalibration,
    TelemetryPayload,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/devices/register", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_device(payload: DeviceRegister, _: dict = Depends(require_admin)):
    db = get_db()

    existing = (
        db.collection(Collections.IOT_DEVICES)
        .where("device_id", "==", payload.device_id)
        .limit(1)
        .get()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device already registered",
        )

    doc_id = str(uuid.uuid4())
    data   = {
        **payload.model_dump(),
        "id": doc_id,
        "device_type": payload.device_type.value,
        "status": "offline",
        "last_ping": None,
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.IOT_DEVICES).document(doc_id).set(data)
    return DeviceResponse(**data)


@router.get("/devices")
async def list_devices(_: dict = Depends(require_admin)):
    db   = get_db()
    docs = db.collection(Collections.IOT_DEVICES).get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str, _: dict = Depends(require_admin)):
    db   = get_db()
    docs = db.collection(Collections.IOT_DEVICES).where("device_id", "==", device_id).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    d = docs[0]
    return DeviceResponse(**{**d.to_dict(), "id": d.id})


@router.post("/devices/{device_id}/ping", status_code=status.HTTP_200_OK)
async def device_ping(device_id: str, payload: DevicePing):
    """Heartbeat from hardware device. No user auth — secured at network/API-key level."""
    db   = get_db()
    docs = db.collection(Collections.IOT_DEVICES).where("device_id", "==", device_id).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not registered")

    updates: dict = {"status": "online", "last_ping": datetime.now(timezone.utc)}
    if payload.firmware_version:
        updates["firmware_version"] = payload.firmware_version
    if payload.ip_address:
        updates["ip_address"] = payload.ip_address

    docs[0].reference.update(updates)
    return {"status": "ok", "server_time": datetime.now(timezone.utc)}


@router.post("/devices/{device_id}/telemetry", status_code=status.HTTP_200_OK)
async def receive_telemetry(device_id: str, payload: TelemetryPayload):
    """Push sensor readings from hardware — flow rate, tamper flag, temperature."""
    db   = get_db()
    docs = db.collection(Collections.IOT_DEVICES).where("device_id", "==", device_id).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not registered")

    docs[0].reference.update({"status": "online", "last_ping": datetime.now(timezone.utc)})

    if payload.nozzle_id:
        nozzle_updates: dict = {"last_seen": datetime.now(timezone.utc)}
        if payload.flow_rate is not None:
            nozzle_updates["current_flow_rate"] = payload.flow_rate
            nozzle_updates["status"]            = "dispensing" if payload.flow_rate > 0 else "idle"
        if payload.total_dispensed is not None:
            nozzle_updates["total_litres_today"] = payload.total_dispensed
        if payload.tamper_detected:
            nozzle_updates["tamper_detected"] = True
            nozzle_updates["status"]          = "tampered"
        try:
            db.collection(Collections.NOZZLES).document(payload.nozzle_id).update(nozzle_updates)
        except Exception:
            logger.exception("Failed to update nozzle %s from telemetry", payload.nozzle_id)

    # Store raw telemetry for analytics and audit
    db.collection(Collections.TELEMETRY_LOGS).add({
        "device_id": device_id,
        **payload.model_dump(),
        "received_at": datetime.now(timezone.utc),
    })

    return {"status": "ok"}


@router.post("/devices/{device_id}/camera/trigger", status_code=status.HTTP_200_OK)
async def trigger_camera(
    device_id: str,
    payload: CameraCapture,
    _: dict = Depends(require_admin),
):
    """Queue a camera capture command for the device to pick up on next poll."""
    db   = get_db()
    docs = db.collection(Collections.IOT_DEVICES).where("device_id", "==", device_id).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    command_id = str(uuid.uuid4())
    db.collection(Collections.DEVICE_COMMANDS).document(command_id).set({
        "id": command_id,
        "device_id": device_id,
        "command": "camera_capture",
        "payload": {"reason": payload.reason},
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    })
    return {"command_id": command_id, "message": "Camera capture command queued"}


@router.put("/devices/{device_id}/calibrate", status_code=status.HTTP_200_OK)
async def calibrate_flow_meter(
    device_id: str,
    payload: FlowCalibration,
    _: dict = Depends(require_admin),
):
    db   = get_db()
    docs = db.collection(Collections.IOT_DEVICES).where("device_id", "==", device_id).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    command_id = str(uuid.uuid4())
    db.collection(Collections.DEVICE_COMMANDS).document(command_id).set({
        "id": command_id,
        "device_id": device_id,
        "command": "flow_meter_calibrate",
        "payload": payload.model_dump(),
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    })
    return {"command_id": command_id, "message": "Calibration command queued"}


@router.get("/devices/{device_id}/connectivity")
async def device_connectivity(device_id: str, _: dict = Depends(require_admin)):
    db   = get_db()
    docs = db.collection(Collections.IOT_DEVICES).where("device_id", "==", device_id).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    data      = docs[0].to_dict()
    last_ping = ensure_utc(data.get("last_ping"))
    now       = datetime.now(timezone.utc)

    # Device is considered online if it pinged within the last 60 seconds
    online = last_ping is not None and (now - last_ping).total_seconds() < 60

    return {
        "device_id": device_id,
        "status": "online" if online else "offline",
        "last_ping": last_ping,
        "ip_address": data.get("ip_address"),
    }


@router.post("/firmware/upload", status_code=status.HTTP_201_CREATED)
async def upload_firmware(
    version: str,
    release_notes: str | None = None,
    is_mandatory: bool = False,
    file: UploadFile = File(...),
    _: dict = Depends(require_admin),
):
    if not all([settings.CLOUDINARY_CLOUD_NAME, settings.CLOUDINARY_API_KEY, settings.CLOUDINARY_API_SECRET]):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firmware storage not configured — set CLOUDINARY_* env vars.",
        )

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )

    db       = get_db()
    contents = await file.read()

    from io import BytesIO
    public_id = f"fuelguard/firmware/{version}/{file.filename}"
    upload_result = cloudinary.uploader.upload(
        BytesIO(contents),
        public_id=public_id,
        resource_type="raw",
        overwrite=False,
    )
    download_url = upload_result["secure_url"]

    fw_id = str(uuid.uuid4())
    data  = {
        "id": fw_id,
        "version": version,
        "release_notes": release_notes,
        "is_mandatory": is_mandatory,
        "download_url": download_url,
        "file_size_bytes": len(contents),
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.IOT_FIRMWARE).document(fw_id).set(data)
    return data


@router.post("/devices/{device_id}/firmware/update", status_code=status.HTTP_200_OK)
async def push_firmware_update(
    device_id: str,
    payload: FirmwareUpdateRequest,
    _: dict = Depends(require_admin),
):
    db   = get_db()
    docs = db.collection(Collections.IOT_DEVICES).where("device_id", "==", device_id).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    fw_docs = (
        db.collection(Collections.IOT_FIRMWARE)
        .where("version", "==", payload.firmware_version)
        .limit(1)
        .get()
    )
    if not fw_docs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Firmware version '{payload.firmware_version}' not found",
        )

    fw_data    = fw_docs[0].to_dict()
    command_id = str(uuid.uuid4())

    db.collection(Collections.DEVICE_COMMANDS).document(command_id).set({
        "id": command_id,
        "device_id": device_id,
        "command": "firmware_update",
        "payload": {
            "version": payload.firmware_version,
            "download_url": fw_data["download_url"],
            "force": payload.force,
        },
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    })
    docs[0].reference.update({
        "firmware_update_status": "pending",
        "target_firmware_version": payload.firmware_version,
    })
    return {"command_id": command_id, "message": "Firmware update command queued"}


@router.get("/devices/{device_id}/firmware/status", response_model=FirmwareStatusResponse)
async def firmware_update_status(device_id: str, _: dict = Depends(require_admin)):
    db   = get_db()
    docs = db.collection(Collections.IOT_DEVICES).where("device_id", "==", device_id).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    data = docs[0].to_dict()
    return FirmwareStatusResponse(
        device_id=device_id,
        current_version=data.get("firmware_version", "unknown"),
        target_version=data.get("target_firmware_version"),
        update_status=data.get("firmware_update_status", "idle"),
        progress_percent=data.get("firmware_update_progress"),
        last_updated=ensure_utc(data.get("last_ping")),
    )
