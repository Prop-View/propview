"""Per-tenant call settings with environment values reserved for local development."""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from db import tenant_connection


@dataclass(frozen=True)
class TenantCallSettings:
    agency_name: str
    broker_transfer_number: str | None
    sms_sender_number: str | None
    time_zone: str
    business_hours: tuple[int, int]
    voice_name: str | None
    greeting: str


def _local_defaults(agency_name: str | None = None) -> TenantCallSettings:
    start_hour = int(os.environ.get("BUSINESS_HOURS_START_HOUR", "9"))
    end_hour = int(os.environ.get("BUSINESS_HOURS_END_HOUR", "17"))
    if not 0 <= start_hour < end_hour <= 24:
        raise ValueError("Business hours environment values must satisfy 0 <= start < end <= 24")
    time_zone = os.environ.get("BUSINESS_TIME_ZONE", "UTC")
    ZoneInfo(time_zone)
    return TenantCallSettings(
        agency_name=agency_name or os.environ.get("AGENCY_NAME", "our brokerage"),
        broker_transfer_number=os.environ.get("BROKER_PHONE_NUMBER"),
        sms_sender_number=os.environ.get("TWILIO_SMS_FROM_NUMBER"),
        time_zone=time_zone,
        business_hours=(start_hour, end_hour),
        voice_name=os.environ.get("GEMINI_VOICE_NAME"),
        greeting=os.environ.get("AGENT_GREETING", "Hello, how can I help you today?"),
    )


async def get_tenant_call_settings(
    tenant_id: str, database_url: str | None, default_agency_name: str | None = None
) -> TenantCallSettings:
    defaults = _local_defaults(default_agency_name)
    if database_url is None:
        return defaults

    async with tenant_connection(tenant_id, database_url) as connection:
        row = await connection.fetchrow(
            """
            SELECT agency_name, broker_transfer_number, sms_sender_number,
                   time_zone, business_hours_start_hour, business_hours_end_hour,
                   voice_name, greeting
            FROM tenant_settings
            WHERE tenant_id = $1
            """,
            tenant_id,
        )

    if row is None:
        return defaults

    time_zone = row["time_zone"] or defaults.time_zone
    ZoneInfo(time_zone)
    start_hour = row["business_hours_start_hour"]
    end_hour = row["business_hours_end_hour"]
    business_hours = (
        (start_hour, end_hour)
        if start_hour is not None and end_hour is not None
        else defaults.business_hours
    )
    return TenantCallSettings(
        agency_name=row["agency_name"] or defaults.agency_name,
        broker_transfer_number=row["broker_transfer_number"] or defaults.broker_transfer_number,
        sms_sender_number=row["sms_sender_number"] or defaults.sms_sender_number,
        time_zone=time_zone,
        business_hours=business_hours,
        voice_name=row["voice_name"] or defaults.voice_name,
        greeting=row["greeting"] or defaults.greeting,
    )
