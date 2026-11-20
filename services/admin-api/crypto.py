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

from cryptography.fernet import Fernet, MultiFernet


def _key_from_environment(name: str) -> bytes:
    key = os.environ.get(name)
    if not key:
        raise RuntimeError(
            f"{name} not set. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return key.encode()


def _get_fernet() -> MultiFernet:
    current_key = _key_from_environment("ENCRYPTION_KEY")
    keys = [Fernet(current_key)]
    previous_key = os.environ.get("ENCRYPTION_KEY_PREVIOUS")
    if previous_key and previous_key.encode() != current_key:
        keys.append(Fernet(previous_key.encode()))
    return MultiFernet(keys)


def encrypt_with_key(plaintext: str, key: str) -> bytes:
    return Fernet(key.encode()).encrypt(plaintext.encode())


def decrypt_with_key(ciphertext: bytes, key: str) -> str:
    return Fernet(key.encode()).decrypt(ciphertext).decode()


def rotate_ciphertext(ciphertext: bytes, old_key: str, new_key: str) -> bytes:
    return MultiFernet([Fernet(new_key.encode()), Fernet(old_key.encode())]).rotate(ciphertext)


def encrypt(plaintext: str) -> bytes:
    return _get_fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    return _get_fernet().decrypt(ciphertext).decode()
