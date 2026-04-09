from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.dependencies import get_current_user, require_admin
from core.firebase import Collections, get_db
from models.nozzle import (
    FlowReading,
    NozzleCreate,
    NozzleResponse,
    NozzleUpdate,
    TamperAlert,
    TamperAlertResolve,
)

router = APIRouter()


@router.get("", response_model=list[NozzleResponse])
async def list_nozzles(
    station_id: str | None = Query(None),
    nozzle_status: str | None = Query(None, alias="status"),
    fuel_type: str | None = Query(None),
    _: dict = Depends(get_current_user),
):
    db    = get_db()
    query = db.collection(Collections.NOZZLES)
    if station_id:
        query = query.where("station_id", "==", station_id)
    if nozzle_status:
        query = query.where("status", "==", nozzle_status)
    if fuel_type:
        query = query.where("fuel_type", "==", fuel_type)
    docs = query.get()
    return [NozzleResponse(**{**d.to_dict(), "id": d.id}) for d in docs]


@router.get("/alerts/tamper")
async def list_tamper_alerts(
    resolved: bool = Query(False),
    _: dict = Depends(require_admin),
):
    db   = get_db()
    docs = db.collection(Collections.TAMPER_ALERTS).where("resolved", "==", resolved).get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@router.get("/{nozzle_id}", response_model=NozzleResponse)
async def get_nozzle(nozzle_id: str, _: dict = Depends(get_current_user)):
    db  = get_db()
    doc = db.collection(Collections.NOZZLES).document(nozzle_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nozzle not found")
    return NozzleResponse(**{**doc.to_dict(), "id": doc.id})


@router.post("", response_model=NozzleResponse, status_code=status.HTTP_201_CREATED)
async def create_nozzle(payload: NozzleCreate, _: dict = Depends(require_admin)):
    db = get_db()

    # Validate station exists before registering the nozzle
    station_doc = db.collection(Collections.STATIONS).document(payload.station_id).get()
    if not station_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station '{payload.station_id}' not found",
        )

    # BLE UUID must be unique across all registered nozzles
    existing_ble = (
        db.collection(Collections.NOZZLES)
        .where("ble_uuid", "==", payload.ble_uuid)
        .limit(1)
        .get()
    )
    if existing_ble:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A nozzle with BLE UUID '{payload.ble_uuid}' is already registered",
        )

    # Hardware serial must be unique
    existing_serial = (
        db.collection(Collections.NOZZLES)
        .where("hardware_serial", "==", payload.hardware_serial)
        .limit(1)
        .get()
    )
    if existing_serial:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Hardware serial '{payload.hardware_serial}' is already registered",
        )

    nozzle_id = str(uuid.uuid4())
    data = {
        **payload.model_dump(),
        "id": nozzle_id,
        # Pydantic model_dump() serialises Enums to their .value automatically
        "fuel_type": payload.fuel_type.value,
        "status": "idle",
        "is_active": True,
        "tamper_detected": False,
        "current_flow_rate": None,
        "total_litres_today": 0.0,
        "last_seen": None,
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.NOZZLES).document(nozzle_id).set(data)
    return NozzleResponse(**data)


@router.put("/{nozzle_id}", response_model=NozzleResponse)
async def update_nozzle(
    nozzle_id: str,
    payload: NozzleUpdate,
    _: dict = Depends(require_admin),
):
    db  = get_db()
    ref = db.collection(Collections.NOZZLES).document(nozzle_id)
    if not ref.get().exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nozzle not found")

    updates = payload.model_dump(exclude_none=True)
    # model_dump() with Enums returns the .value string when mode="json" or
    # when the enum is a str-enum (which ours are), so no extra .value call needed.
    ref.update(updates)
    return NozzleResponse(**{**ref.get().to_dict(), "id": nozzle_id})


@router.delete("/{nozzle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nozzle(nozzle_id: str, _: dict = Depends(require_admin)):
    db  = get_db()
    ref = db.collection(Collections.NOZZLES).document(nozzle_id)
    if not ref.get().exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nozzle not found")
    ref.delete()


@router.get("/{nozzle_id}/readings")
async def get_nozzle_readings(nozzle_id: str, _: dict = Depends(get_current_user)):
    db  = get_db()
    doc = db.collection(Collections.NOZZLES).document(nozzle_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nozzle not found")
    d = doc.to_dict()
    return {
        "nozzle_id": nozzle_id,
        "current_flow_rate": d.get("current_flow_rate"),
        "total_litres_today": d.get("total_litres_today", 0.0),
        "status": d.get("status"),
        "last_seen": d.get("last_seen"),
    }


@router.post("/{nozzle_id}/readings", status_code=status.HTTP_200_OK)
async def push_flow_reading(nozzle_id: str, payload: FlowReading):
    """IoT device pushes a live flow-meter reading. No auth — secured at network level."""
    db  = get_db()
    ref = db.collection(Collections.NOZZLES).document(nozzle_id)
    if not ref.get().exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nozzle not found")
    ref.update({
        "current_flow_rate": payload.flow_rate,
        "total_litres_today": payload.total_dispensed,
        "status": "dispensing" if payload.flow_rate > 0 else "idle",
        "last_seen": datetime.now(timezone.utc),
    })
    return {"status": "ok"}


@router.get("/{nozzle_id}/status")
async def get_nozzle_status(nozzle_id: str, _: dict = Depends(get_current_user)):
    db  = get_db()
    doc = db.collection(Collections.NOZZLES).document(nozzle_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nozzle not found")
    d = doc.to_dict()
    return {
        "nozzle_id": nozzle_id,
        "status": d.get("status"),
        "tamper_detected": d.get("tamper_detected"),
    }


@router.post("/{nozzle_id}/tamper-alert", status_code=status.HTTP_201_CREATED)
async def report_tamper(nozzle_id: str, payload: TamperAlert):
    """IoT device reports a tamper event. No auth — secured at network level."""
    db       = get_db()
    alert_id = str(uuid.uuid4())
    alert_data = {
        "id": alert_id,
        "nozzle_id": nozzle_id,
        "alert_type": payload.alert_type,
        "description": payload.description,
        "resolved": False,
        "resolution_note": None,
        "timestamp": payload.timestamp or datetime.now(timezone.utc),
    }
    db.collection(Collections.TAMPER_ALERTS).document(alert_id).set(alert_data)
    db.collection(Collections.NOZZLES).document(nozzle_id).update({
        "tamper_detected": True,
        "status": "tampered",
    })
    return {"alert_id": alert_id, "message": "Tamper alert recorded"}


@router.patch("/alerts/{alert_id}/resolve")
async def resolve_tamper_alert(
    alert_id: str,
    payload: TamperAlertResolve,
    _: dict = Depends(require_admin),
):
    db  = get_db()
    ref = db.collection(Collections.TAMPER_ALERTS).document(alert_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    nozzle_id = doc.to_dict().get("nozzle_id")
    ref.update({
        "resolved": True,
        "resolution_note": payload.resolution_note,
        "resolved_at": datetime.now(timezone.utc),
    })

    if nozzle_id:
        # Only reset tamper flag — do NOT blindly set status to "idle".
        # The nozzle may legitimately be offline or in maintenance.
        db.collection(Collections.NOZZLES).document(nozzle_id).update(
            {"tamper_detected": False}
        )

    return {"message": "Alert resolved"}
