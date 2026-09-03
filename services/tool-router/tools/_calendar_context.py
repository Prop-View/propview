"""
Shared helper for check_calendar_slots and book_site_visit: builds a
GoogleCalendarClient from a tenant's stored (encrypted) credentials.
Factored out so both tools fail the same clear way when a tenant hasn't
configured calendar integration yet, rather than each reimplementing the
lookup + decrypt + "what if it's missing" handling.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import asyncpg

# append, not insert(0, ...): both admin-api and tool-router have their
# own main.py/db.py -- inserting these at the front of sys.path would let
# admin-api's same-named modules shadow tool-router's own on any
# not-yet-cached import elsewhere in the process. Append only adds a
# fallback location, never overrides an already-resolvable local import.
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "admin-api"))
from crypto import decrypt  # noqa: E402

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "scheduling"))
from calendar_client import GoogleCalendarClient  # noqa: E402


class CalendarNotConfiguredError(ValueError):
    def __init__(self, tenant_id: str):
        super().__init__(f"No calendar integration configured for tenant {tenant_id!r}")


async def get_calendar_client(connection: asyncpg.Connection, tenant_id: str) -> GoogleCalendarClient:
    row = await connection.fetchrow(
        "SELECT calendar_provider, encrypted_calendar_credentials FROM tenant_settings WHERE tenant_id = $1",
        tenant_id,
    )
    if row is None or row["encrypted_calendar_credentials"] is None:
        raise CalendarNotConfiguredError(tenant_id)

    # Only Google Calendar is implemented -- the plan names Cal.com as an
    # alternative but doesn't require both for MVP; a tenant configured
    # with a different provider string gets the same clear error rather
    # than silently being treated as Google.
    if row["calendar_provider"] != "google":
        raise CalendarNotConfiguredError(tenant_id)

    credentials_dict = json.loads(decrypt(row["encrypted_calendar_credentials"]))
    return GoogleCalendarClient(credentials_dict)
