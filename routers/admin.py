from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.dependencies import require_admin
from core.firebase import Collections, get_db
from core.security import hash_password
from models.user import EmployeeUpdate, UserCreate

router = APIRouter()


@router.get("/overview")
async def dashboard_overview(_: dict = Depends(require_admin)):
    db          = get_db()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    active_sessions_docs = db.collection(Collections.SESSIONS).where("status", "==", "active").get()
    tx_today_docs        = db.collection(Collections.TRANSACTIONS).where("created_at", ">=", today_start).get()
    open_alert_docs      = db.collection(Collections.FRAUD_ALERTS).where("status", "==", "open").get()

    tx_today      = [d.to_dict() for d in tx_today_docs]
    revenue_today = sum(t.get("total_amount", 0) for t in tx_today)

    litres_list   = [t.get("litres_dispensed", 0) for t in tx_today if t.get("litres_dispensed")]
    avg_litres    = round(sum(litres_list) / len(litres_list), 2) if litres_list else 0.0

    return {
        "active_sessions": len(list(active_sessions_docs)),
        "revenue_today_pkr": round(revenue_today, 2),
        "transactions_today": len(tx_today),
        "open_fraud_alerts": len(list(open_alert_docs)),
        "avg_litres_per_transaction": avg_litres,
        "generated_at": datetime.now(timezone.utc),
    }


@router.get("/nozzles/live")
async def live_nozzle_status(_: dict = Depends(require_admin)):
    db   = get_db()
    docs = db.collection(Collections.NOZZLES).get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@router.get("/employees")
async def list_employees(
    is_active: bool = Query(True),
    _: dict = Depends(require_admin),
):
    db   = get_db()
    docs = (
        db.collection(Collections.USERS)
        .where("role", "==", "employee")
        .where("is_active", "==", is_active)
        .get()
    )
    employees = []
    for d in docs:
        data = d.to_dict()
        data.pop("password_hash", None)
        employees.append(data)
    return {"total": len(employees), "items": employees}


@router.post("/employees", status_code=status.HTTP_201_CREATED)
async def add_employee(payload: UserCreate, _: dict = Depends(require_admin)):
    db = get_db()
    existing = db.collection(Collections.USERS).where("email", "==", payload.email).limit(1).get()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    uid  = str(uuid.uuid4())
    data = {
        "uid": uid,
        "email": payload.email,
        "full_name": payload.full_name,
        "phone": payload.phone,
        "role": "employee",
        "password_hash": hash_password(payload.password),
        "avatar_url": None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.USERS).document(uid).set(data)
    data.pop("password_hash")
    return data


@router.put("/employees/{employee_id}")
async def update_employee(
    employee_id: str,
    payload: EmployeeUpdate,
    _: dict = Depends(require_admin),
):
    db  = get_db()
    ref = db.collection(Collections.USERS).document(employee_id)
    doc = ref.get()
    if not doc.exists or doc.to_dict().get("role") != "employee":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided to update",
        )
    ref.update(updates)
    return {"message": "Employee updated"}


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(employee_id: str, _: dict = Depends(require_admin)):
    db  = get_db()
    ref = db.collection(Collections.USERS).document(employee_id)
    doc = ref.get()
    if not doc.exists or doc.to_dict().get("role") != "employee":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    ref.delete()


@router.get("/complaints")
async def list_complaints(
    complaint_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    _: dict = Depends(require_admin),
):
    db    = get_db()
    query = db.collection(Collections.COMPLAINTS)
    if complaint_status:
        query = query.where("status", "==", complaint_status)
    docs = query.order_by("created_at", direction="DESCENDING").limit(limit).get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@router.post("/complaints", status_code=status.HTTP_201_CREATED)
async def submit_complaint(
    user_id: str,
    subject: str,
    description: str,
    _: dict = Depends(require_admin),
):
    db           = get_db()
    complaint_id = str(uuid.uuid4())
    data         = {
        "id": complaint_id,
        "user_id": user_id,
        "subject": subject,
        "description": description,
        "status": "open",
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.COMPLAINTS).document(complaint_id).set(data)
    return data


@router.patch("/complaints/{complaint_id}")
async def update_complaint_status(
    complaint_id: str,
    complaint_status: str = Query(..., alias="status"),
    resolution_note: str | None = Query(None),
    _: dict = Depends(require_admin),
):
    db  = get_db()
    ref = db.collection(Collections.COMPLAINTS).document(complaint_id)
    if not ref.get().exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
    update: dict = {"status": complaint_status, "updated_at": datetime.now(timezone.utc)}
    if resolution_note:
        update["resolution_note"] = resolution_note
    ref.update(update)
    return {"message": "Complaint updated"}


@router.get("/analytics")
async def business_analytics(_: dict = Depends(require_admin)):
    db          = get_db()
    now         = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    tx_docs      = db.collection(Collections.TRANSACTIONS).where("created_at", ">=", month_start).get()
    transactions = [d.to_dict() for d in tx_docs]

    total_revenue = sum(t.get("total_amount", 0) for t in transactions)
    total_litres  = sum(t.get("litres_dispensed", 0) for t in transactions)

    by_fuel: dict[str, float]    = {}
    by_payment: dict[str, int]   = {}

    for t in transactions:
        ft = t.get("fuel_type", "unknown")
        pm = t.get("payment_method", "unknown")
        by_fuel[ft]    = by_fuel.get(ft, 0.0) + t.get("total_amount", 0)
        by_payment[pm] = by_payment.get(pm, 0) + 1

    fraud_count    = len(db.collection(Collections.FRAUD_ALERTS).where("status", "==", "open").get())
    active_nozzles = len(db.collection(Collections.NOZZLES).where("status", "==", "dispensing").get())

    return {
        "period": "current_month",
        "total_transactions": len(transactions),
        "total_revenue_pkr": round(total_revenue, 2),
        "total_litres_dispensed": round(total_litres, 2),
        "revenue_by_fuel_type": {k: round(v, 2) for k, v in by_fuel.items()},
        "transactions_by_payment": by_payment,
        "open_fraud_alerts": fraud_count,
        "active_nozzles_now": active_nozzles,
    }
