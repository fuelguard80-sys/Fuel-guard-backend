from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import partial

from core.config import settings

logger = logging.getLogger(__name__)


def _send_sync(to: str, subject: str, html_body: str) -> None:
    """Synchronous SMTP send — runs in a thread pool to avoid blocking the event loop."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.EMAIL_FROM, to, msg.as_string())


async def send_email(to: str, subject: str, html_body: str) -> None:
    """
    Send an email without blocking the asyncio event loop.

    smtplib is synchronous blocking I/O. Calling it directly inside an async
    function would stall the entire event loop for every request in flight.
    We off-load it to the default thread pool executor instead.
    """
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, partial(_send_sync, to, subject, html_body))
    except Exception:
        # Log the real error server-side but never propagate it to the caller —
        # a failed email must not crash a user-facing request.
        logger.exception("Failed to send email to %s (subject: %s)", to, subject)
