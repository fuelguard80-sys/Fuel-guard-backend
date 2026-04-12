from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone, timedelta
from io import BytesIO

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.dependencies import get_current_user, require_admin
from core.firebase import Collections, ensure_utc, get_db
from models.session import (
    DeviceSessionRequest,
    QRGenerateRequest,
    QRGenerateResponse,
    QRScanRequest,
    SessionCloseRequest,
    SessionLinkRequest,
    SessionResponse,
)

router = APIRouter()


def _generate_qr_base64(data: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@router.post("/generate-qr", response_model=QRGenerateResponse, status_code=status.HTTP_201_CREATED)
async def generate_qr(payload: QRGenerateRequest, _: dict = Depends(require_admin)):
    db = get_db()

    nozzle_doc = db.collection(Collections.NOZZLES).document(payload.nozzle_id).get()
    if not nozzle_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nozzle not found")

    session_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload.expires_in_seconds)
    qr_data    = f"fuelguard://session/{session_id}"

    session_doc = {
        "id": session_id,
        "nozzle_id": payload.nozzle_id,
        "user_id": None,
        "status": "pending",
        "qr_data": qr_data,
        "expires_at": expires_at,
        "started_at": None,
        "ended_at": None,
        "total_litres": 0.0,
        "total_amount": 0.0,
        "transaction_id": None,
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.SESSIONS).document(session_id).set(session_doc)

    return QRGenerateResponse(
        session_id=session_id,
        nozzle_id=payload.nozzle_id,
        qr_data=qr_data,
        qr_image_base64=_generate_qr_base64(qr_data),
        expires_at=expires_at,
    )


@router.post("/scan", status_code=status.HTTP_200_OK)
async def scan_qr(payload: QRScanRequest, current_user: dict = Depends(get_current_user)):
    db   = get_db()
    docs = db.collection(Collections.SESSIONS).where("qr_data", "==", payload.qr_data).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid QR code")

    session    = docs[0].to_dict()
    session_id = session["id"]
    session_ref = db.collection(Collections.SESSIONS).document(session_id)

    if session["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is not available (status: {session['status']})",
        )

    now        = datetime.now(timezone.utc)
    expires_at = ensure_utc(session.get("expires_at"))
    if expires_at and now > expires_at:
        session_ref.update({"status": "timed_out"})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="QR code has expired")

    # Use a Firestore transaction to prevent a race condition where two concurrent
    # requests scan the same QR code and both pass the "pending" status check.
    @db.transaction()
    def _activate(transaction, ref):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists or snapshot.to_dict().get("status") != "pending":
            raise ValueError("session_not_pending")
        transaction.update(ref, {
            "status": "active",
            "user_id": current_user["uid"],
            "started_at": now,
        })

    try:
        _activate(session_ref)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session was already claimed by another request",
        )

    return {"session_id": session_id, "status": "active", "nozzle_id": session["nozzle_id"]}


@router.post("/start", status_code=status.HTTP_200_OK)
async def start_device_session(
    payload: DeviceSessionRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Device-initiated session — used when the app connects to the ESP32 via
    WiFi QR and queries /info for the nozzle_id instead of scanning a
    backend-generated QR code.
    """
    db = get_db()

    nozzle_doc = db.collection(Collections.NOZZLES).document(payload.nozzle_id).get()
    if not nozzle_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nozzle not found")

    # If an active session already exists for this nozzle, reuse it.
    existing = (
        db.collection(Collections.SESSIONS)
        .where("nozzle_id", "==", payload.nozzle_id)
        .where("status", "==", "active")
        .limit(1)
        .get()
    )
    if existing:
        s = existing[0].to_dict()
        return {"session_id": s["id"], "nozzle_id": payload.nozzle_id, "status": "active"}

    session_id = str(uuid.uuid4())
    now        = datetime.now(timezone.utc)
    session_doc = {
        "id":             session_id,
        "nozzle_id":      payload.nozzle_id,
        "user_id":        current_user["uid"],
        "status":         "active",
        "qr_data":        None,
        "started_at":     now,
        "ended_at":       None,
        "expires_at":     None,
        "total_litres":   0.0,
        "total_amount":   0.0,
        "transaction_id": None,
        "created_at":     now,
    }
    db.collection(Collections.SESSIONS).document(session_id).set(session_doc)
    return {"session_id": session_id, "nozzle_id": payload.nozzle_id, "status": "active"}


@router.get("/active")
async def list_active_sessions(_: dict = Depends(require_admin)):
    db   = get_db()
    docs = db.collection(Collections.SESSIONS).where("status", "==", "active").get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@router.get("/concurrent")
async def check_concurrent_sessions(
    nozzle_id: str = Query(...),
    _: dict = Depends(require_admin),
):
    db   = get_db()
    docs = (
        db.collection(Collections.SESSIONS)
        .where("nozzle_id", "==", nozzle_id)
        .where("status", "==", "active")
        .get()
    )
    sessions = [{"id": d.id, **d.to_dict()} for d in docs]
    return {"nozzle_id": nozzle_id, "concurrent_count": len(sessions), "sessions": sessions}


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, _: dict = Depends(get_current_user)):
    db  = get_db()
    doc = db.collection(Collections.SESSIONS).document(session_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return SessionResponse(**{**doc.to_dict(), "id": doc.id})


@router.get("")
async def list_sessions(
    session_status: str | None = Query(None, alias="status"),
    nozzle_id: str | None = Query(None),
    user_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: dict = Depends(require_admin),
):
    db    = get_db()
    query = db.collection(Collections.SESSIONS)
    if session_status:
        query = query.where("status", "==", session_status)
    if nozzle_id:
        query = query.where("nozzle_id", "==", nozzle_id)
    if user_id:
        query = query.where("user_id", "==", user_id)

    docs = query.get()
    items = [{"id": d.id, **d.to_dict()} for d in docs]
    return items[offset: offset + limit]


@router.post("/{session_id}/link", status_code=status.HTTP_200_OK)
async def link_user_to_session(
    session_id: str,
    payload: SessionLinkRequest,
    _: dict = Depends(require_admin),
):
    db  = get_db()
    ref = db.collection(Collections.SESSIONS).document(session_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if doc.to_dict()["status"] != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session is not active")
    ref.update({"user_id": payload.user_id})
    return {"message": "User linked to session"}


@router.post("/{session_id}/close", status_code=status.HTTP_200_OK)
async def close_session(
    session_id: str,
    payload: SessionCloseRequest,
    _: dict = Depends(get_current_user),
):
    db  = get_db()
    ref = db.collection(Collections.SESSIONS).document(session_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if doc.to_dict()["status"] not in ("active", "pending"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session is already closed")
    ref.update({
        "status": "completed",
        "ended_at": datetime.now(timezone.utc),
        "close_reason": payload.reason,
    })
    return {"message": "Session closed"}


@router.post("/timeout-check", status_code=status.HTTP_200_OK)
async def auto_close_timed_out_sessions():
    """
    Background job endpoint — auto-closes expired pending sessions.
    Should be called by a scheduled task, not end-users.
    """
    db  = get_db()
    now = datetime.now(timezone.utc)

    docs   = db.collection(Collections.SESSIONS).where("status", "==", "pending").get()
    closed = 0
    for doc in docs:
        expires_at = ensure_utc(doc.to_dict().get("expires_at"))
        if expires_at and now > expires_at:
            db.collection(Collections.SESSIONS).document(doc.id).update({"status": "timed_out"})
            closed += 1

    return {"timed_out_sessions_closed": closed}
