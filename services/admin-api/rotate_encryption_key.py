"""Re-encrypt all tenant calendar and webhook secrets with a new Fernet key."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent.parent / "orchestrator"))

load_dotenv()

from db import close_pool, tenant_connection  # noqa: E402
from crypto import rotate_ciphertext  # noqa: E402
from tenant_registry import list_registry_tenants  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rotate_encryption_key")


async def rotate_all_tenant_keys(database_url: str, old_key: str, new_key: str) -> dict[str, int]:
    if old_key == new_key:
        raise ValueError("Old and new encryption keys must differ")

    counts = {"calendar_credentials": 0, "webhook_signing_secrets": 0}
    tenants = await list_registry_tenants(database_url)
    for tenant in tenants:
        tenant_id = tenant["slug"]
        async with tenant_connection(tenant_id) as connection:
            calendar = await connection.fetchrow(
                """
                SELECT encrypted_calendar_credentials
                FROM tenant_settings
                WHERE tenant_id = $1 AND encrypted_calendar_credentials IS NOT NULL
                """,
                tenant_id,
            )
            if calendar:
                await connection.execute(
                    """
                    UPDATE tenant_settings
                    SET encrypted_calendar_credentials = $1, updated_at = now()
                    WHERE tenant_id = $2
                    """,
                    rotate_ciphertext(calendar["encrypted_calendar_credentials"], old_key, new_key),
                    tenant_id,
                )
                counts["calendar_credentials"] += 1

            webhooks = await connection.fetch(
                """
                SELECT id, encrypted_signing_secret
                FROM tenant_webhooks
                WHERE tenant_id = $1
                ORDER BY id
                """,
                tenant_id,
            )
            for webhook in webhooks:
                await connection.execute(
                    """
                    UPDATE tenant_webhooks
                    SET encrypted_signing_secret = $1, updated_at = now()
                    WHERE tenant_id = $2 AND id = $3
                    """,
                    rotate_ciphertext(webhook["encrypted_signing_secret"], old_key, new_key),
                    tenant_id,
                    webhook["id"],
                )
                counts["webhook_signing_secrets"] += 1

        logger.info("Rotated encryption data for tenant %s", tenant_id)
    return counts


async def _main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    old_key = os.environ.get("OLD_ENCRYPTION_KEY")
    new_key = os.environ.get("NEW_ENCRYPTION_KEY")
    if not database_url or not old_key or not new_key:
        raise RuntimeError(
            "DATABASE_URL, OLD_ENCRYPTION_KEY, and NEW_ENCRYPTION_KEY are required"
        )

    try:
        counts = await rotate_all_tenant_keys(database_url, old_key, new_key)
        logger.info("Key rotation complete: %s", counts)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
