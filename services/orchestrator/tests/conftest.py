"""Resets the orchestrator's module-level database pool between tests.

`db.py` keeps one `asyncpg.Pool` and one `asyncio.Lock` for the lifetime of
the process. That is correct for the worker, which has exactly one event loop
forever, but wrong under pytest-asyncio, which gives each test function its own
loop: the second test to touch the pool inherits a pool (and a lock) bound to
the first test's already-closed loop and fails with "Event loop is closed" or
"pool is closed".

This is the same trap CLAUDE.md section 13 records for tool-router, which only
avoided it because its tests share one TestClient fixture. The orchestrator
grew its shared pool in Phase 2 and nothing reset it, so every DB-backed test
after the first in a module failed.

Both resets are deliberately synchronous: `Pool.terminate()` and rebinding the
lock need no running loop, so this works for sync and async tests alike and
avoids closing the pool from a *different* loop than the one that opened it --
which is what a separate `asyncio.run(close_pool())` would do.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database_pool():
    yield
    try:
        db.terminate_pool()
    except Exception:
        # Best effort only. If pytest-asyncio already closed the test's loop,
        # the pool's transports are gone and terminate() raises from deep in
        # asyncio (on Windows: AttributeError inside proactor_events). The
        # connections die with the loop either way; what matters for the next
        # test is that the module globals below no longer point at them.
        pass
    db._pool = None
    db._pool_database_url = None
    # The lock caches the loop it was first awaited on, so a fresh pool on a
    # fresh loop still fails against a stale lock without this.
    db._pool_lock = asyncio.Lock()
