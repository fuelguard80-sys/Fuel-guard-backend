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
            {"role": "user",   "content": message},
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
