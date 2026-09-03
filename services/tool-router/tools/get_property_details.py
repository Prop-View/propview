"""get_property_details tool -- named in the Sprint Plan's Sprint 3 feature
list alongside search_properties, though not broken out as its own PROP
ticket. Built alongside search_properties since it shares the same
tool-dispatch infrastructure and is trivial once that exists."""

from __future__ import annotations

import asyncpg
from pydantic import BaseModel

from db import record_to_dict


class GetPropertyDetailsArgs(BaseModel):
    property_id: int


async def get_property_details(pool: asyncpg.Pool, args: GetPropertyDetailsArgs, tenant_id: str = "default") -> dict | None:
    row = await pool.fetchrow(
        """
        SELECT id, address, city, state, property_type, status, beds, baths, sqft,
               price, hoa_fee, amenities, floor_plan_url, listing_agent
        FROM properties
        WHERE tenant_id = $1 AND id = $2
        """,
        tenant_id,
        args.property_id,
    )
    return record_to_dict(row) if row is not None else None
