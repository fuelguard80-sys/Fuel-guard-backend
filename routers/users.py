from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.dependencies import get_current_user, require_admin
from core.firebase import Collections, get_db
from core.security import hash_password, verify_password
from models.user import PasswordChange, RoleUpdate, StatusUpdate, UserProfile, UserUpdate

router = APIRouter()


@router.get("/me", response_model=UserProfile)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    return UserProfile(**current_user)


@router.put("/me", response_model=UserProfile)
async def update_my_profile(
    payload: UserUpdate,
    current_user: dict = Depends(get_current_user),
):
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided to update")

    db  = get_db()
    uid = current_user["uid"]
    db.collection(Collections.USERS).document(uid).update(updates)
    updated = db.collection(Collections.USERS).document(uid).get().to_dict()
    updated.pop("password_hash", None)
    return UserProfile(**updated)


@router.put("/me/password", status_code=status.HTTP_200_OK)
async def change_password(
    payload: PasswordChange,
    current_user: dict = Depends(get_current_user),
):
    db  = get_db()
    uid = current_user["uid"]
    doc = db.collection(Collections.USERS).document(uid).get().to_dict()

    if not verify_password(payload.current_password, doc.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    db.collection(Collections.USERS).document(uid).update(
        {"password_hash": hash_password(payload.new_password)}
    )
    return {"message": "Password changed successfully"}


@router.get("")
async def list_users(
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: dict = Depends(require_admin),
):
    db    = get_db()
    query = db.collection(Collections.USERS)
    if role:
        query = query.where("role", "==", role)
    if is_active is not None:
        query = query.where("is_active", "==", is_active)

    docs  = query.get()
    users = []
    for doc in docs:
        d = doc.to_dict()
        d.pop("password_hash", None)
        users.append(d)

    # Cursor-less offset applied in Python — acceptable for admin user lists
    # which are typically small. For large datasets, switch to cursor pagination.
    paginated = users[offset: offset + limit]
    return {"total": len(users), "items": paginated}


@router.get("/{user_id}")
async def get_user(user_id: str, _: dict = Depends(require_admin)):
    db  = get_db()
    doc = db.collection(Collections.USERS).document(user_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    d = doc.to_dict()
    d.pop("password_hash", None)
    return d


@router.put("/{user_id}/role")
async def update_role(
    user_id: str,
    payload: RoleUpdate,
    _: dict = Depends(require_admin),
):
    db  = get_db()
    ref = db.collection(Collections.USERS).document(user_id)
    if not ref.get().exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    ref.update({"role": payload.role.value})
    return {"message": "Role updated", "role": payload.role.value}


@router.patch("/{user_id}/status")
async def update_status(
    user_id: str,
    payload: StatusUpdate,
    _: dict = Depends(require_admin),
):
    db  = get_db()
    ref = db.collection(Collections.USERS).document(user_id)
    if not ref.get().exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    ref.update({"is_active": payload.is_active})
    return {"message": "Status updated", "is_active": payload.is_active}


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, current_user: dict = Depends(require_admin)):
    if user_id == current_user["uid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )
    db  = get_db()
    ref = db.collection(Collections.USERS).document(user_id)
    if not ref.get().exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    ref.delete()
