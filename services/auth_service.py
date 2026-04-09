from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import httpx

from core.config import settings
from core.firebase import Collections
from core.security import generate_otp, verify_otp_value
from utils.email import send_email

logger = logging.getLogger(__name__)


async def send_otp_email(email: str, db) -> None:
    """
    Generate a cryptographically secure OTP, persist it with an expiry,
    and dispatch it via email.
    """
    otp = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

    db.collection(Collections.OTP_STORE).document(email).set({
        "otp": otp,
        "expires_at": expires_at,
        "email": email,
    })

    subject = "Fuel Guard — OTP Verification"
    body = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: auto;">
      <h2 style="color: #1C2536;">Fuel Guard Password Reset</h2>
      <p>Use the following one-time code to reset your password:</p>
      <div style="font-size: 32px; font-weight: bold; letter-spacing: 8px;
                  text-align: center; padding: 16px 0; color: #1C2536;">
        {otp}
      </div>
      <p style="color: #637381; font-size: 13px;">
        This code expires in <strong>{settings.OTP_EXPIRE_MINUTES} minutes</strong>.<br>
        If you did not request a password reset, you can safely ignore this email.
      </p>
    </div>
    """
    await send_email(to=email, subject=subject, html_body=body)


def verify_stored_otp(db, email: str, otp: str) -> bool:
    """
    Validate an OTP against the stored record.

    - Uses constant-time comparison (secrets.compare_digest) to prevent
      timing side-channel attacks.
    - Rejects expired OTPs using proper UTC-aware comparison.
    """
    doc = db.collection(Collections.OTP_STORE).document(email).get()
    if not doc.exists:
        return False

    data = doc.to_dict()
    stored_otp: str = data.get("otp", "")

    # Constant-time comparison — prevents timing attacks
    if not verify_otp_value(stored_otp, otp):
        return False

    expires_at: datetime | None = data.get("expires_at")
    if expires_at is not None:
        now = datetime.now(timezone.utc)
        # Normalise to UTC-aware before comparing
        exp_aware = (
            expires_at.replace(tzinfo=timezone.utc)
            if expires_at.tzinfo is None
            else expires_at.astimezone(timezone.utc)
        )
        if now > exp_aware:
            return False

    return True


async def query_chatbot(message: str, user: dict) -> str:
    """
    Forward a sanitised user message to the OpenAI Chat Completions API.

    The user message is not further modified — prompt injection is mitigated
    by the system prompt, which does not include any user-controlled content.
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not configured — chatbot unavailable.")
        return "Support chat is not available at this time. Please contact us via email."

    system_prompt = (
        "You are Fuel Guard Support Assistant, a helpful and concise AI for the Fuel Guard "
        "mobile app. Answer only questions about fuel dispensing, transactions, station discovery, "
        "fraud alerts, and general app usage. Do not reveal internal system details. "
        "If a question is outside your scope, politely say so."
    )

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "max_tokens": 500,
        "temperature": 0.4,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        logger.error("OpenAI API returned %s: %s", exc.response.status_code, exc.response.text)
    except Exception:
        logger.exception("Unexpected error querying chatbot")

    return "I'm unable to process your request right now. Please try again in a moment."
