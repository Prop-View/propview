"""
Seeds the `properties` table from a listings CSV.

Distinct from ingest_listings.py, which embeds free text into
`knowledge_base_chunks` for RAG. This fills the structured table that
`search_properties` actually queries, which nothing else in this repo
populated -- an empty `properties` table means every search returns zero
rows while the agent otherwise behaves perfectly, which is a confusing
failure to debug from a call transcript.

Sale-only by default: `properties` has no transaction_type column, and
mixing sale prices (~$150k-2M) with monthly rents (~$850-3k) in one
`price` column silently corrupts search -- `max_price=500000` matches
every rental, and ORDER BY price ASC floats them all to the top. Pass
--include-rent only if the schema has grown a way to tell them apart.

Usage:
    python ingest_properties.py <csv-path> [--tenant-id default] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://propview_app:devpassword@localhost:5433/propview_dev"
)

# properties_status_check allows exactly these.
ALLOWED_STATUS = {"active", "pending", "sold", "off_market"}

# "3360 Whitestone Blvd, Cedar Park, TX 78613" -> ("TX", "78613")
STATE_ZIP = re.compile(r",\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?\s*$")


def parse_row(row: dict) -> dict | None:
    """Maps one CSV row to a properties insert, or None if unusable."""
    status = (row.get("status") or "").strip().lower()
    if status not in ALLOWED_STATUS:
        return None

    address = (row.get("address") or "").strip()
    match = STATE_ZIP.search(address)
    state, zip_code = (match.group(1), match.group(2)) if match else ("TX", None)

    amenities = [a for a in (row.get("amenities") or "").split("|") if a]

    # recurring_fee is per fee_period; the column is a monthly HOA fee.
    fee = float(row.get("recurring_fee") or 0)
    if (row.get("fee_period") or "").strip().lower() == "annual":
        fee = round(fee / 12, 2)

    def num(key, cast, default=None):
        raw = (row.get(key) or "").strip()
        try:
            return cast(raw) if raw else default
        except ValueError:
            return default

    return {
        "address": address,
        "city": (row.get("city_or_locality") or "").strip(),
        "state": state,
        "zip_code": zip_code,
        "property_type": (row.get("property_type") or "").strip().lower(),
        "status": status,
        "beds": num("beds", int),
        "baths": num("baths", float),
        "sqft": num("floor_area", int),
        "price": num("price", float, 0.0),
        "hoa_fee": fee,
        "listing_agent": (row.get("listing_agent_name") or "").strip() or None,
        "amenities": json.dumps(amenities),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--tenant-id", default="default")
    ap.add_argument("--include-rent", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows, skipped_txn, skipped_status = [], 0, 0
    with open(args.csv_path, newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            if not args.include_rent and (raw.get("transaction_type") or "").strip().lower() != "sale":
                skipped_txn += 1
                continue
            parsed = parse_row(raw)
            if parsed is None:
                skipped_status += 1
                continue
            rows.append(parsed)

    print(f"parsed {len(rows)} rows")
    print(f"  skipped (not a sale listing): {skipped_txn}")
    print(f"  skipped (status not in {sorted(ALLOWED_STATUS)}): {skipped_status}")
    if rows:
        prices = sorted(r["price"] for r in rows)
        cities = sorted({r["city"] for r in rows})
        print(f"  price range: ${prices[0]:,.0f} - ${prices[-1]:,.0f}")
        print(f"  cities ({len(cities)}): {', '.join(cities)}")

    if args.dry_run or not rows:
        print("\n(dry run -- nothing written)")
        return

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            # RLS is fail-closed: without this the insert is rejected
            # rather than silently landing in the wrong tenant.
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", args.tenant_id)
            await conn.executemany(
                """
                INSERT INTO properties (
                    tenant_id, address, city, state, zip_code, property_type,
                    status, beds, baths, sqft, price, hoa_fee, listing_agent, amenities
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)
                """,
                [
                    (
                        args.tenant_id, r["address"], r["city"], r["state"], r["zip_code"],
                        r["property_type"], r["status"], r["beds"], r["baths"], r["sqft"],
                        r["price"], r["hoa_fee"], r["listing_agent"], r["amenities"],
                    )
                    for r in rows
                ],
            )
            total = await conn.fetchval("SELECT count(*) FROM properties")
        print(f"\ninserted {len(rows)} rows; properties now holds {total} for tenant {args.tenant_id!r}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
