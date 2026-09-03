"""
Symmetric encryption for calendar credentials at rest (tenant_settings.
encrypted_calendar_credentials). Partially anticipates PROP-407 ("API key
encryption for third-party calendar integrations") -- that ticket is
blocked on PROP-403 (the actual Calendar API integration, not built), but
there's no reason to ever store a real credential in plaintext even
before that integration exists, so this is built now rather than left
for later.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY not set. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode())


def encrypt(plaintext: str) -> bytes:
    return _get_fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    return _get_fernet().decrypt(ciphertext).decode()
