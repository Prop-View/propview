"""Tenant-owned booking and messaging configuration with local-dev fallbacks."""

from __future__ import annotations

import os
from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class TenantOperationalSettings:
    agency_name: str
    sms_sender_number: str | None
    whatsapp_sender_number: str | None
    time_zone: str
    business_hours: tuple[int, int]


async def get_tenant_operational_settings(
    connection: asyncpg.Connection, tenant_id: str
) -> TenantOperationalSettings:
    row = await connection.fetchrow(
        """
        SELECT agency_name, sms_sender_number, whatsapp_sender_number, time_zone,
               business_hours_start_hour, business_hours_end_hour
        FROM tenant_settings
        WHERE tenant_id = $1
        """,
        tenant_id,
    )

    start_hour = int(os.environ.get("BUSINESS_HOURS_START_HOUR", "9"))
    end_hour = int(os.environ.get("BUSINESS_HOURS_END_HOUR", "17"))
    if not 0 <= start_hour < end_hour <= 24:
        raise ValueError("BUSINESS_HOURS_START_HOUR and BUSINESS_HOURS_END_HOUR must define a valid range")

    return TenantOperationalSettings(
        agency_name=row["agency_name"] if row and row["agency_name"] else os.environ.get("AGENCY_NAME", "our brokerage"),
        sms_sender_number=(
            row["sms_sender_number"] if row and row["sms_sender_number"] else os.environ.get("TWILIO_SMS_FROM_NUMBER")
        ),
        whatsapp_sender_number=(
            row["whatsapp_sender_number"]
            if row and row["whatsapp_sender_number"]
            else os.environ.get("TWILIO_WHATSAPP_FROM_NUMBER")
        ),
        time_zone=(
            row["time_zone"] if row and row["time_zone"] else os.environ.get("BUSINESS_TIME_ZONE", "UTC")
        ),
        business_hours=(
            (
                row["business_hours_start_hour"],
                row["business_hours_end_hour"],
            )
            if row
            and row["business_hours_start_hour"] is not None
            and row["business_hours_end_hour"] is not None
            else (start_hour, end_hour)
        ),
    )
