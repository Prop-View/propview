"""
PROP-304: search_properties tool -- schema + parameterized SQL execution.

SQL injection prevention (PROP-307): column names and SQL structure are
fixed strings this code controls; every user-supplied VALUE goes through
asyncpg's $n positional parameters (true wire-protocol parameterization,
not string escaping), never concatenated into the query text. Enum-like
fields are additionally constrained by Pydantic's Literal type, which
rejects invalid values before a query is ever built.
"""

from __future__ import annotations

from typing import Literal

import asyncpg
from pydantic import BaseModel, Field

from db import record_to_dict

PropertyType = Literal["house", "condo", "townhouse", "land"]
PropertyStatus = Literal["active", "pending", "sold", "off_market"]


class SearchPropertiesArgs(BaseModel):
    city: str | None = None
    property_type: PropertyType | None = None
    min_beds: int | None = Field(None, ge=0, le=20)
    max_beds: int | None = Field(None, ge=0, le=20)
    min_baths: float | None = Field(None, ge=0, le=20)
    min_price: float | None = Field(None, ge=0)
    max_price: float | None = Field(None, ge=0)
    status: PropertyStatus = "active"
    limit: int = Field(10, ge=1, le=50)


async def search_properties(pool: asyncpg.Pool, args: SearchPropertiesArgs, tenant_id: str = "default") -> list[dict]:
    conditions = ["tenant_id = $1", "status = $2"]
    params: list = [tenant_id, args.status]

    def add(condition_column_expr: str, value) -> None:
        params.append(value)
        conditions.append(f"{condition_column_expr} ${len(params)}")

    if args.city:
        add("city ILIKE", args.city)
    if args.property_type:
        add("property_type =", args.property_type)
    if args.min_beds is not None:
        add("beds >=", args.min_beds)
    if args.max_beds is not None:
        add("beds <=", args.max_beds)
    if args.min_baths is not None:
        add("baths >=", args.min_baths)
    if args.min_price is not None:
        add("price >=", args.min_price)
    if args.max_price is not None:
        add("price <=", args.max_price)

    params.append(args.limit)
    query = f"""
        SELECT id, address, city, state, property_type, beds, baths, sqft, price, hoa_fee, amenities
        FROM properties
        WHERE {' AND '.join(conditions)}
        ORDER BY price ASC
        LIMIT ${len(params)}
    """

    rows = await pool.fetch(query, *params)
    return [record_to_dict(row) for row in rows]
