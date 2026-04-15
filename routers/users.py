from __future__ import annotations

import logging
import uuid
from io import BytesIO

import cloudinary
import cloudinary.uploader
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from core.config import settings
from core.dependencies import get_current_user, require_admin
from core.firebase import Collections, get_db
from core.security import hash_password, verify_password
from models.user import PasswordChange, RoleUpdate, StatusUpdate, UserProfile, UserUpdate

logger = logging.getLogger(__name__)

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


@router.post("/me/avatar", response_model=UserProfile, status_code=status.HTTP_200_OK)
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    if not all([settings.CLOUDINARY_CLOUD_NAME, settings.CLOUDINARY_API_KEY, settings.CLOUDINARY_API_SECRET]):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Avatar storage not configured",
        )

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )

    uid = current_user["uid"]
    contents = await file.read()

    public_id = f"fuelguard/avatars/{uid}/{uuid.uuid4()}"
    try:
        result = cloudinary.uploader.upload(
            BytesIO(contents),
            public_id=public_id,
            resource_type="image",
            overwrite=True,
            transformation=[{"width": 512, "height": 512, "crop": "fill", "gravity": "face"}],
        )
    except Exception:
        logger.exception("Cloudinary avatar upload failed for user %s", uid)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload avatar — please try again",
        )

    avatar_url = result["secure_url"]
    db = get_db()
    db.collection(Collections.USERS).document(uid).update({"avatar_url": avatar_url})
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
