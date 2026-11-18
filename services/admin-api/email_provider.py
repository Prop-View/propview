"""Provider-agnostic email interface with SMTP as the default transport."""

from __future__ import annotations

import asyncio
import os
import smtplib
from email.message import EmailMessage


class EmailDeliveryError(RuntimeError):
    pass


def _send_smtp(recipient: str, subject: str, body: str) -> None:
    host = os.environ.get("SMTP_HOST")
    sender = os.environ.get("SMTP_FROM")
    if not host or not sender:
        raise EmailDeliveryError("SMTP_HOST and SMTP_FROM must be configured")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    port = int(os.environ.get("SMTP_PORT", "587"))
    timeout = float(os.environ.get("SMTP_TIMEOUT_SECONDS", "10"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    use_starttls = os.environ.get("SMTP_USE_STARTTLS", "true").lower() in {"1", "true", "yes"}

    try:
        with smtplib.SMTP(host, port, timeout=timeout) as client:
            if use_starttls:
                client.starttls()
            if username:
                client.login(username, password or "")
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("SMTP delivery failed") from exc


async def send_email(recipient: str, subject: str, body: str) -> None:
    await asyncio.to_thread(_send_smtp, recipient, subject, body)
