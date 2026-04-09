from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.dependencies import get_current_user, require_admin
from core.firebase import Collections, Increment, get_db
from models.fleet import (
    BudgetSet,
    DriverAssign,
    DriverCreate,
    DriverResponse,
    ExpenseCreate,
    ExpenseResponse,
    VehicleCreate,
    VehicleResponse,
    VehicleUpdate,
)

router = APIRouter()


# ── Vehicles ──────────────────────────────────────────────────────────────────

@router.get("/vehicles")
async def list_vehicles(current_user: dict = Depends(get_current_user)):
    db    = get_db()
    query = db.collection(Collections.FLEET_VEHICLES)
    if current_user.get("role") not in ("admin", "super_admin"):
        query = query.where("owner_uid", "==", current_user["uid"])
    docs = query.get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@router.post("/vehicles", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def add_vehicle(payload: VehicleCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    existing = (
        db.collection(Collections.FLEET_VEHICLES)
        .where("registration_number", "==", payload.registration_number)
        .limit(1)
        .get()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration number already registered",
        )

    vehicle_id = str(uuid.uuid4())
    data = {
        **payload.model_dump(),
        "id": vehicle_id,
        "owner_uid": payload.owner_uid or current_user["uid"],
        "assigned_driver_uid": None,
        "is_active": True,
        "total_fuel_consumed": 0.0,
        "total_expense": 0.0,
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.FLEET_VEHICLES).document(vehicle_id).set(data)
    return VehicleResponse(**data)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(vehicle_id: str, current_user: dict = Depends(get_current_user)):
    db  = get_db()
    doc = db.collection(Collections.FLEET_VEHICLES).document(vehicle_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    data = doc.to_dict()
    if data["owner_uid"] != current_user["uid"] and current_user["role"] not in ("admin", "super_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return VehicleResponse(**{**data, "id": doc.id})


@router.put("/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: str,
    payload: VehicleUpdate,
    current_user: dict = Depends(get_current_user),
):
    db  = get_db()
    ref = db.collection(Collections.FLEET_VEHICLES).document(vehicle_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if doc.to_dict()["owner_uid"] != current_user["uid"] and current_user["role"] not in (
        "admin", "super_admin"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    updates = payload.model_dump(exclude_none=True)
    ref.update(updates)
    return VehicleResponse(**{**ref.get().to_dict(), "id": vehicle_id})


@router.delete("/vehicles/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(vehicle_id: str, current_user: dict = Depends(get_current_user)):
    db  = get_db()
    ref = db.collection(Collections.FLEET_VEHICLES).document(vehicle_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if doc.to_dict()["owner_uid"] != current_user["uid"] and current_user["role"] not in (
        "admin", "super_admin"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    ref.delete()


@router.get("/vehicles/{vehicle_id}/consumption")
async def fuel_consumption(vehicle_id: str, current_user: dict = Depends(get_current_user)):
    db  = get_db()
    doc = db.collection(Collections.FLEET_VEHICLES).document(vehicle_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    expenses = (
        db.collection(Collections.FLEET_EXPENSES)
        .where("vehicle_id", "==", vehicle_id)
        .where("category", "==", "fuel")
        .get()
    )

    monthly: dict[str, dict] = {}
    for e in expenses:
        data  = e.to_dict()
        edate = data.get("expense_date")
        if not edate:
            continue
        key = str(edate)[:7]  # "YYYY-MM"
        if key not in monthly:
            monthly[key] = {"litres": 0.0, "amount": 0.0}
        monthly[key]["litres"] += data.get("litres", 0.0)
        monthly[key]["amount"] += data.get("amount", 0.0)

    vehicle_data = doc.to_dict()
    return {
        "vehicle_id": vehicle_id,
        "registration_number": vehicle_data.get("registration_number"),
        "total_fuel_consumed": vehicle_data.get("total_fuel_consumed", 0.0),
        "monthly_breakdown": monthly,
    }


# ── Expenses ──────────────────────────────────────────────────────────────────

@router.get("/expenses")
async def list_expenses(
    vehicle_id: str | None = Query(None),
    category: str | None = Query(None),
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    db    = get_db()
    query = db.collection(Collections.FLEET_EXPENSES)
    if vehicle_id:
        query = query.where("vehicle_id", "==", vehicle_id)
    if category:
        query = query.where("category", "==", category)
    if current_user["role"] not in ("admin", "super_admin"):
        query = query.where("user_id", "==", current_user["uid"])

    docs  = query.order_by("expense_date", direction="DESCENDING").get()
    items = []
    for d in docs:
        data = {"id": d.id, **d.to_dict()}
        if month and year:
            edate = data.get("expense_date")
            if edate and hasattr(edate, "month") and (edate.month != month or edate.year != year):
                continue
        items.append(data)

    return {"total": len(items), "items": items}


@router.post("/expenses", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
async def log_expense(payload: ExpenseCreate, current_user: dict = Depends(get_current_user)):
    db         = get_db()
    expense_id = str(uuid.uuid4())
    data = {
        **payload.model_dump(),
        "id": expense_id,
        "user_id": current_user["uid"],
        "category": payload.category.value,
        "expense_date": payload.expense_date or date.today(),
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.FLEET_EXPENSES).document(expense_id).set(data)

    # Increment vehicle totals — never overwrite
    if payload.category.value == "fuel" and payload.litres:
        db.collection(Collections.FLEET_VEHICLES).document(payload.vehicle_id).update({
            "total_fuel_consumed": Increment(payload.litres),
            "total_expense": Increment(payload.amount),
        })
    else:
        db.collection(Collections.FLEET_VEHICLES).document(payload.vehicle_id).update({
            "total_expense": Increment(payload.amount),
        })

    return ExpenseResponse(**data)


# ── Budget ────────────────────────────────────────────────────────────────────

@router.get("/budget")
async def get_budget(
    vehicle_id: str | None = Query(None),
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    db  = get_db()
    now = datetime.now(timezone.utc)
    m   = month or now.month
    y   = year  or now.year

    query = (
        db.collection(Collections.BUDGETS)
        .where("user_id", "==", current_user["uid"])
        .where("month", "==", m)
        .where("year", "==", y)
    )
    if vehicle_id:
        query = query.where("vehicle_id", "==", vehicle_id)

    docs = query.limit(1).get()
    if not docs:
        return {"message": "No budget set for this period"}

    data = docs[0].to_dict()

    # Calculate actual spend from expenses
    exp_query = db.collection(Collections.FLEET_EXPENSES).where("user_id", "==", current_user["uid"])
    if vehicle_id:
        exp_query = exp_query.where("vehicle_id", "==", vehicle_id)

    expenses = exp_query.get()
    spent = sum(
        e.to_dict().get("amount", 0)
        for e in expenses
        if (
            edate := e.to_dict().get("expense_date")
        ) and hasattr(edate, "month") and edate.month == m and edate.year == y
    )

    data["spent_amount"] = round(spent, 2)
    data["remaining"]    = round(data.get("budget_amount", 0) - spent, 2)
    return data


@router.put("/budget")
async def set_budget(payload: BudgetSet, current_user: dict = Depends(get_current_user)):
    db        = get_db()
    budget_id = (
        f"{current_user['uid']}_{payload.vehicle_id or 'all'}_{payload.year}_{payload.month}"
    )
    data = {
        "id": budget_id,
        "user_id": current_user["uid"],
        **payload.model_dump(),
        "updated_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.BUDGETS).document(budget_id).set(data, merge=True)
    return {"message": "Budget set", "budget_id": budget_id}


# ── Drivers ───────────────────────────────────────────────────────────────────

@router.get("/drivers")
async def list_drivers(_: dict = Depends(get_current_user)):
    db   = get_db()
    docs = db.collection(Collections.FLEET_DRIVERS).get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@router.post("/drivers", response_model=DriverResponse, status_code=status.HTTP_201_CREATED)
async def add_driver(payload: DriverCreate, _: dict = Depends(get_current_user)):
    db        = get_db()
    driver_id = str(uuid.uuid4())
    data = {
        **payload.model_dump(),
        "id": driver_id,
        "assigned_vehicle_id": None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.FLEET_DRIVERS).document(driver_id).set(data)
    return DriverResponse(**data)


@router.put("/vehicles/{vehicle_id}/driver")
async def assign_driver(
    vehicle_id: str,
    payload: DriverAssign,
    _: dict = Depends(get_current_user),
):
    db  = get_db()
    ref = db.collection(Collections.FLEET_VEHICLES).document(vehicle_id)
    if not ref.get().exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    ref.update({"assigned_driver_uid": payload.driver_uid})

    driver_docs = (
        db.collection(Collections.FLEET_DRIVERS)
        .where("uid", "==", payload.driver_uid)
        .limit(1)
        .get()
    )
    if driver_docs:
        driver_docs[0].reference.update({"assigned_vehicle_id": vehicle_id})

    return {"message": "Driver assigned to vehicle"}
