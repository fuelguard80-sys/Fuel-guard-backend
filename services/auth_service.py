from __future__ import annotations

import logging

import httpx
from firebase_admin import auth as firebase_auth

from core.config import settings

logger = logging.getLogger(__name__)


async def send_firebase_password_reset(email: str) -> None:
    """
    Trigger a Firebase Auth password-reset email via the Identity Toolkit REST API.

    Firebase delivers the email through Google's own mail infrastructure — no SMTP
    configuration is required.  The resulting link is hosted by Firebase and can be
    customised in the Firebase Console (Authentication → Templates).

    Raises httpx.HTTPStatusError if Firebase returns a non-2xx response.
    """
    url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode"
        f"?key={settings.FIREBASE_API_KEY}"
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json={
            "requestType": "PASSWORD_RESET",
            "email": email,
        })
        response.raise_for_status()


def create_firebase_auth_user(
    uid: str,
    email: str,
    password: str,
    display_name: str,
) -> None:
    """
    Mirror a new Firestore user into Firebase Auth so that Firebase can send
    email-verification and password-reset emails on behalf of the account.

    Errors are logged but do not propagate — a Firebase Auth failure must never
    prevent a successful signup from completing.
    """
    try:
        firebase_auth.create_user(
            uid=uid,
            email=email,
            password=password,
            display_name=display_name,
            email_verified=False,
        )
    except firebase_auth.EmailAlreadyExistsError:
        logger.warning("Firebase Auth user already exists for %s — skipping creation.", email)
    except Exception:
        logger.exception(
            "Failed to create Firebase Auth user for uid=%s email=%s. "
            "The Firestore user was created successfully; Firebase Auth can be "
            "synced later.",
            uid,
            email,
        )


def get_firebase_user_email(firebase_id_token: str) -> str:
    """
    Verify a Firebase ID token and return the email address it belongs to.

    Raises firebase_admin.auth.InvalidIdTokenError (or a subclass) if the token
    is invalid, expired, or was issued for a different Firebase project.
    """
    decoded = firebase_auth.verify_id_token(firebase_id_token)
    email: str | None = decoded.get("email")
    if not email:
        raise ValueError("Firebase ID token does not contain an email claim.")
    return email


_SYSTEM_PROMPT = """You are the FuelGuard Support Assistant — a concise, friendly AI embedded inside the FuelGuard mobile app.

## What FuelGuard is
FuelGuard is a smart fuel management platform used in Pakistan. It connects IoT-enabled fuel nozzles at petrol stations to a mobile app and cloud backend. Users scan a QR code at a pump, the app connects to the nozzle's WiFi hotspot (SSID: FuelMonitor), and fuel dispensing is monitored in real-time. Every transaction is recorded with litres dispensed, amount (PKR), timestamp, and optional evidence photo.

## Key concepts you know about
- **QR fueling flow**: Scan nozzle QR → phone connects to FuelMonitor WiFi → live session starts → fuel dispensed → session ends → transaction saved
- **Sessions**: A fueling session tracks real-time flow data from the ESP32 nozzle device. Status: active → completed or failed
- **Transactions**: Each completed session creates a transaction. States: completed, pending, failed. Amount is in PKR (Pakistani Rupees). Payment is always cash.
- **Nozzles**: Physical IoT devices at pumps identified by IDs like NZ001. Each belongs to a station.
- **Stations**: Fuel stations listed in the app with prices and locations
- **Fraud detection**: The system compares dispensed volume reported by the nozzle vs expected. Discrepancies trigger fraud alerts.
- **Evidence photos**: Photo taken at the pump, stored in Cloudinary, attached to the transaction
- **Fleet management**: Business users can track multiple vehicles, drivers, and fleet fuel expenses
- **Account**: Users have a profile with name, phone, avatar. Password can be changed in settings.
- **OTA firmware**: Nozzle devices receive firmware updates from the backend

## How to respond
- Be brief and direct — 1 to 4 sentences max unless a step-by-step is needed
- Use plain language, no technical jargon unless the user asks
- If a question is completely outside FuelGuard (e.g. general knowledge, other apps), politely decline
- Never reveal API keys, internal endpoints, database structure, or credentials
- If you don't know something specific to the user's account, tell them to contact support at support@fuelguard.com
"""


async def query_chatbot(message: str, user: dict) -> str:
    """Call Gemini Flash with a FuelGuard system prompt and return the reply."""
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not configured — chatbot unavailable.")
        return "Support chat is not available at this time. Please contact us via email."

    payload = {
        "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": message}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 400,
        },
    }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error(
                    "Gemini API returned %s: %s", response.status_code, response.text
                )
                return "I'm unable to process your request right now. Please try again in a moment."
            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                logger.error("Gemini returned no candidates: %s", data)
                return "I'm unable to process your request right now. Please try again in a moment."
            return candidates[0]["content"]["parts"][0]["text"].strip()
    except Exception:
        logger.exception("Unexpected error querying Gemini chatbot")

    return "I'm unable to process your request right now. Please try again in a moment."
