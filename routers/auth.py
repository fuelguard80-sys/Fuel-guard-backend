from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from core.dependencies import get_current_user
from core.firebase import Collections, get_db
from core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from models.user import (
    ChatbotMessage,
    ChatbotResponse,
    ForgotPasswordRequest,
    OTPVerify,
    PasswordReset,
    RefreshTokenRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
)
from services.auth_service import query_chatbot, send_otp_email, verify_stored_otp

router = APIRouter()


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserCreate):
    db = get_db()

    existing = db.collection(Collections.USERS).where("email", "==", payload.email).limit(1).get()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    uid = str(uuid.uuid4())
    user_data = {
        "uid": uid,
        "email": payload.email,
        "full_name": payload.full_name,
        "phone": payload.phone,
        "role": payload.role.value,
        "password_hash": hash_password(payload.password),
        "avatar_url": None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.USERS).document(uid).set(user_data)

    token_payload = {"uid": uid, "role": payload.role.value}
    return TokenResponse(
        access_token=create_access_token(token_payload),
        refresh_token=create_refresh_token(token_payload),
        uid=uid,
        role=payload.role.value,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin):
    db = get_db()

    docs = db.collection(Collections.USERS).where("email", "==", payload.email).limit(1).get()
    if not docs:
        # Same message for wrong email and wrong password — prevents user enumeration
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    user = docs[0].to_dict()
    if not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact support.",
        )

    token_payload = {"uid": user["uid"], "role": user["role"]}
    return TokenResponse(
        access_token=create_access_token(token_payload),
        refresh_token=create_refresh_token(token_payload),
        uid=user["uid"],
        role=user["role"],
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(_: dict = Depends(get_current_user)):
    # Stateless JWT — the client discards its tokens.
    # For full revocation, add the jti claim to a Firestore denylist here.
    return {"message": "Logged out successfully"}


@router.post("/refresh-token", response_model=TokenResponse)
async def refresh_token(payload: RefreshTokenRequest):
    try:
        data = decode_token(payload.refresh_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if data.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Provided token is not a refresh token",
        )

    uid  = data["uid"]
    role = data["role"]
    token_payload = {"uid": uid, "role": role}
    return TokenResponse(
        access_token=create_access_token(token_payload),
        refresh_token=create_refresh_token(token_payload),
        uid=uid,
        role=role,
    )


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(payload: ForgotPasswordRequest):
    db = get_db()
    docs = db.collection(Collections.USERS).where("email", "==", payload.email).limit(1).get()

    # Always return the same response regardless of whether the email exists.
    # Revealing which emails are registered is a user-enumeration vulnerability.
    if docs:
        await send_otp_email(payload.email, db)

    return {"message": "If that email is registered, an OTP has been sent"}


@router.post("/verify-otp", status_code=status.HTTP_200_OK)
async def verify_otp(payload: OTPVerify):
    db = get_db()
    if not verify_stored_otp(db, payload.email, payload.otp):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OTP")
    return {"message": "OTP verified", "email": payload.email}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(payload: PasswordReset):
    db = get_db()

    if not verify_stored_otp(db, payload.email, payload.otp):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OTP")

    docs = db.collection(Collections.USERS).where("email", "==", payload.email).limit(1).get()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    uid = docs[0].to_dict()["uid"]
    db.collection(Collections.USERS).document(uid).update(
        {"password_hash": hash_password(payload.new_password)}
    )
    # Invalidate OTP immediately after a successful reset
    db.collection(Collections.OTP_STORE).document(payload.email).delete()

    return {"message": "Password reset successfully"}


@router.post("/chatbot", response_model=ChatbotResponse)
async def chatbot(payload: ChatbotMessage, current_user: dict = Depends(get_current_user)):
    reply = await query_chatbot(payload.message, current_user)
    return ChatbotResponse(reply=reply)
