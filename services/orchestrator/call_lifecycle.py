"""Process-local call admission and drain state for worker shutdown."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_active_calls = 0
_draining = False


class WorkerDraining(RuntimeError):
    pass


def register_active_call() -> bool:
    global _active_calls
    with _lock:
        if _draining:
            return False
        _active_calls += 1
        return True


def unregister_active_call() -> None:
    global _active_calls
    with _lock:
        if _active_calls <= 0:
            raise RuntimeError("Cannot unregister a call when no call is active")
        _active_calls -= 1


def request_drain() -> int:
    global _draining
    with _lock:
        _draining = True
        return _active_calls


def is_draining() -> bool:
    with _lock:
        return _draining


def active_call_count() -> int:
    with _lock:
        return _active_calls
