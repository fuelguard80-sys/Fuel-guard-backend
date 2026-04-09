from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN       = "admin"
    EMPLOYEE    = "employee"
    CUSTOMER    = "customer"
    DRIVER      = "driver"


class UserCreate(BaseModel):
    email: EmailStr
    password: str    = Field(min_length=8)
    full_name: str   = Field(min_length=2)
    phone: Optional[str] = None
    role: UserRole   = UserRole.CUSTOMER


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserProfile(BaseModel):
    uid: str
    email: str
    full_name: str
    phone: Optional[str]   = None
    role: UserRole
    avatar_url: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None


class UserUpdate(BaseModel):
    full_name: Optional[str]  = None
    phone: Optional[str]      = None
    avatar_url: Optional[str] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class PasswordReset(BaseModel):
    """
    Used after the user resets their password via the Firebase Auth email link.
    The Flutter app signs in with Firebase Auth to obtain a fresh ID token, then
    calls /auth/reset-password so the backend can verify identity and sync the
    bcrypt hash stored in Firestore.
    """
    firebase_id_token: str
    new_password: str = Field(min_length=8)


class RoleUpdate(BaseModel):
    role: UserRole


class StatusUpdate(BaseModel):
    is_active: bool


class EmployeeUpdate(BaseModel):
    """Used by admin to update employee profile fields."""
    full_name: Optional[str]  = None
    phone: Optional[str]      = None
    avatar_url: Optional[str] = None
    is_active: Optional[bool] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    uid: str
    role: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ChatbotMessage(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class ChatbotResponse(BaseModel):
    reply: str
