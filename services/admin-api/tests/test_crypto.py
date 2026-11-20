from __future__ import annotations

from cryptography.fernet import Fernet

from crypto import decrypt, decrypt_with_key, encrypt, encrypt_with_key, rotate_ciphertext


def test_encrypt_decrypt_accepts_current_and_previous_keys(monkeypatch):
    current_key = Fernet.generate_key().decode()
    previous_key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", current_key)
    monkeypatch.setenv("ENCRYPTION_KEY_PREVIOUS", previous_key)

    previous_ciphertext = encrypt_with_key("calendar-token", previous_key)
    current_ciphertext = encrypt("new-calendar-token")

    assert decrypt(previous_ciphertext) == "calendar-token"
    assert decrypt(current_ciphertext) == "new-calendar-token"


def test_rotation_helper_reencrypts_ciphertext_with_new_key():
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    original = encrypt_with_key("webhook-secret", old_key)

    rotated = rotate_ciphertext(original, old_key, new_key)

    assert rotated != original
    assert decrypt_with_key(rotated, new_key) == "webhook-secret"
