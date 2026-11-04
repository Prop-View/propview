"""Seed script: provisions a tenant via the Admin API, uploads properties,
then inserts CRM + call data directly into Postgres (since those are
created by the orchestrator/tool-router during live calls, not the Admin API).

Run: PLATFORM_OPERATOR_TOKEN=<token> python -I seed.py
Requires: Admin API running on port 8100, Postgres running.
Set PLATFORM_OPERATOR_TOKEN env var (from services/admin-api/.env).
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx

API_BASE = os.environ.get("API_URL", "http://localhost:8100")
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://propview_app:devpassword@localhost/propview_dev"
)
PLATFORM_TOKEN = os.environ["PLATFORM_OPERATOR_TOKEN"]
TENANT_ID = os.environ.get("TENANT_ID", "sunrise-realty")


async def main():
    client = httpx.AsyncClient(base_url=API_BASE, timeout=30)

    # 1. Provision tenant
    print("Provisioning tenant...")
    r = await client.post(
        f"/admin/tenants/{TENANT_ID}/provision",
        headers={"Authorization": f"Bearer {PLATFORM_TOKEN}"},
    )
    if r.status_code == 200:
        api_key = r.json()["admin_api_key"]
        print(f"  Tenant: {TENANT_ID}")
        print(f"  API Key: {api_key}")
    else:
        print(f"  Provision failed: {r.status_code} {r.text}")
        sys.exit(1)

    auth = {"Authorization": f"Bearer {api_key}"}

    # 2. Set branding
    print("Setting branding...")
    await client.put(
        f"/admin/tenants/{TENANT_ID}/branding",
        headers=auth,
        json={"agency_name": "Sunrise Realty"},
    )

    # 3. Upload properties
    print("Uploading properties...")
    listings = [
        {"address": "142 Oak Valley Drive", "city": "Austin", "state": "TX", "property_type": "house", "status": "active", "beds": 4, "baths": 3.0, "sqft": 2850, "price": 625000, "listing_agent": "Mike Reynolds", "amenities": ["pool", "garage", "smart home"]},
        {"address": "88 Riverside Blvd #12A", "city": "Austin", "state": "TX", "property_type": "condo", "status": "active", "beds": 2, "baths": 2.0, "sqft": 1200, "price": 385000, "listing_agent": "Sarah Miller", "amenities": ["gym", "rooftop", "concierge"]},
        {"address": "501 Magnolia Lane", "city": "Round Rock", "state": "TX", "property_type": "house", "status": "active", "beds": 3, "baths": 2.5, "sqft": 2100, "price": 475000, "listing_agent": "Mike Reynolds", "amenities": ["garage", "yard", "updated kitchen"]},
        {"address": "77 Congress Ave #8B", "city": "Austin", "state": "TX", "property_type": "condo", "status": "pending", "beds": 1, "baths": 1.0, "sqft": 780, "price": 295000, "listing_agent": "Sarah Miller", "amenities": ["downtown", "balcony"]},
        {"address": "320 Cedar Park Rd", "city": "Cedar Park", "state": "TX", "property_type": "townhouse", "status": "active", "beds": 3, "baths": 2.0, "sqft": 1650, "price": 410000, "listing_agent": "James Lee", "amenities": ["garage", "patio", "community pool"]},
        {"address": "1200 Lake Travis Way", "city": "Lakeway", "state": "TX", "property_type": "house", "status": "active", "beds": 5, "baths": 4.0, "sqft": 4200, "price": 1250000, "listing_agent": "Mike Reynolds", "amenities": ["lake view", "dock", "wine cellar", "theater"]},
        {"address": "45 South Lamar #3C", "city": "Austin", "state": "TX", "property_type": "condo", "status": "sold", "beds": 2, "baths": 2.0, "sqft": 1050, "price": 420000, "listing_agent": "Sarah Miller", "amenities": ["gym", "pool"]},
        {"address": "890 Brushy Creek Rd", "city": "Round Rock", "state": "TX", "property_type": "house", "status": "active", "beds": 4, "baths": 3.0, "sqft": 2600, "price": 550000, "listing_agent": "James Lee", "amenities": ["garage", "yard", "solar panels"]},
        {"address": "15 East 6th Street #PH1", "city": "Austin", "state": "TX", "property_type": "condo", "status": "active", "beds": 3, "baths": 3.0, "sqft": 2400, "price": 890000, "listing_agent": "Sarah Miller", "amenities": ["penthouse", "rooftop", "valet"]},
        {"address": "4400 Bee Cave Rd", "city": "Austin", "state": "TX", "property_type": "house", "status": "active", "beds": 3, "baths": 2.0, "sqft": 1900, "price": 520000, "listing_agent": "James Lee", "amenities": ["hill country views", "screened porch"]},
        {"address": "200 Barton Springs Rd #5A", "city": "Austin", "state": "TX", "property_type": "condo", "status": "active", "beds": 2, "baths": 1.0, "sqft": 950, "price": 345000, "listing_agent": "Sarah Miller", "amenities": ["pool", "near greenbelt"]},
        {"address": "7725 Parmer Lane", "city": "Austin", "state": "TX", "property_type": "house", "status": "active", "beds": 4, "baths": 2.5, "sqft": 2200, "price": 490000, "listing_agent": "Mike Reynolds", "amenities": ["new construction", "open floor plan"]},
    ]
    r = await client.post(
        f"/admin/tenants/{TENANT_ID}/listings",
        headers=auth,
        json={"listings": listings},
    )
    prop_ids = r.json().get("ids", [])
    print(f"  Inserted {len(prop_ids)} properties")

    await client.aclose()

    # 4. Direct DB inserts for CRM + call data
    print("Inserting contacts, leads, calls, appointments, analytics...")
    conn = await asyncpg.connect(DATABASE_URL)

    try:
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TENANT_ID)

        # Contacts
        contacts = [
            ("Sarah Chen", "+15552345678", "sarah.chen@email.com"),
            ("Marcus Johnson", "+15558765432", "marcus.j@email.com"),
            ("Emily Rodriguez", "+15551112233", "emily.r@email.com"),
            ("Lisa Thompson", "+15553344556", None),
            ("Ana Vasquez", "+15559900112", "ana.v@email.com"),
            ("David Park", "+15557788990", "david.park@email.com"),
            ("Rachel Kim", "+15552233441", "rachel.k@email.com"),
            ("James Wright", "+15556677883", None),
            ("Tom Bradley", "+15551239876", "tom.b@email.com"),
            ("Nina Patel", "+15555566771", "nina.p@email.com"),
            ("Kevin Moore", "+15554433221", None),
            ("Diana Cruz", "+15558877665", "diana.c@email.com"),
        ]
        contact_ids = []
        for name, phone, email in contacts:
            cid = await conn.fetchval(
                """INSERT INTO contacts (tenant_id, full_name, phone_number, email)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                TENANT_ID, name, phone, email,
            )
            contact_ids.append(cid)

        # Leads with BANT data
        now = datetime.now(timezone.utc)
        lead_data = [
            # (contact_idx, property_idx, intent, budget_min, budget_max, timeline, decision_maker, priority, status)
            (0, 0, "buy", 450000, 650000, "immediate", "joint", "high", "appointment_set"),
            (1, 4, "buy", 500000, 750000, "1-3mo", "solo", "medium", "qualified"),
            (2, 2, "buy", 300000, 500000, "1-3mo", "joint", "high", "appointment_set"),
            (3, 5, "buy", 700000, 1000000, "immediate", "solo", "high", "qualified"),
            (4, 1, "rent", None, None, "immediate", "solo", "high", "appointment_set"),
            (5, 7, "buy", 250000, 400000, "3-6mo", "other", "medium", "qualified"),
            (6, 3, "rent", None, None, "1-3mo", "solo", "medium", "new"),
            (7, None, "browsing", None, None, "exploring", None, "low", "new"),
            (8, None, "sell", None, None, "6mo+", "solo", "low", "new"),
            (9, None, "browsing", None, None, "exploring", None, "low", "new"),
            (10, 9, "buy", 400000, 600000, "1-3mo", "joint", "medium", "qualified"),
            (11, 8, "buy", 800000, 1000000, "immediate", "solo", "high", "appointment_set"),
        ]
        lead_ids = []
        for i, (ci, pi, intent, bmin, bmax, tl, dm, pri, st) in enumerate(lead_data):
            pid = prop_ids[pi] if pi is not None and pi < len(prop_ids) else None
            lid = await conn.fetchval(
                """INSERT INTO leads (tenant_id, contact_id, property_id, intent, budget_min, budget_max,
                   timeline, decision_maker, priority, status, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$11) RETURNING id""",
                TENANT_ID, contact_ids[ci], pid, intent, bmin, bmax, tl, dm, pri, st,
                now - timedelta(days=12 - i, hours=i * 3),
            )
            lead_ids.append(lid)

        # Appointments
        appt_data = [
            (0, 0, 1, "confirmed", "Mike Reynolds"),
            (2, 2, 1, "scheduled", "Mike Reynolds"),
            (4, 1, 2, "scheduled", "Sarah Miller"),
            (1, 4, 2, "scheduled", "James Lee"),
            (6, 3, 3, "scheduled", "Sarah Miller"),
            (11, 8, 1, "scheduled", "Sarah Miller"),
            (5, 7, -1, "completed", "James Lee"),
            (8, 5, -2, "no_show", "Mike Reynolds"),
            (10, 9, -3, "completed", "James Lee"),
        ]
        for ci_idx, pi_idx, day_offset, status, agent in appt_data:
            pid = prop_ids[pi_idx] if pi_idx < len(prop_ids) else None
            sched = now + timedelta(days=day_offset, hours=10)
            sms_at = sched - timedelta(hours=1) if status in ("confirmed", "completed") else None
            await conn.execute(
                """INSERT INTO appointments (tenant_id, lead_id, property_id, scheduled_at, status, agent_name, confirmation_sms_sent_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                TENANT_ID, lead_ids[ci_idx], pid, sched, status, agent, sms_at,
            )

        # Interactions (calls)
        call_data = [
            ("call-001", 0, 0, 252, "booked",   12, 1),
            ("call-002", 1, 1, 168, "qualified", 8,  2),
            ("call-003", 2, 2, 363, "booked",   16, 3),
            ("call-004", None, None, 82,  "dropped",    4,  4),
            ("call-005", 5, 5, 235, "qualified", 10, 5),
            ("call-006", 3, 3, 318, "transferred", 14, 5),
            ("call-007", 7, 7, 150, "nurture",  6,  6),
            ("call-008", 4, 4, 285, "booked",   12, 6),
            ("call-009", 10, 10, 195, "qualified", 8, 7),
            ("call-010", 11, 11, 340, "booked", 15, 7),
            ("call-011", 6, 6, 120, "nurture", 5, 8),
            ("call-012", 9, 9, 90,  "dropped", 3, 9),
            ("call-013", 0, 0, 180, "booked", 9, 9),
            ("call-014", 5, 5, 210, "qualified", 10, 10),
            ("call-015", 1, 1, 270, "booked", 13, 10),
            ("call-016", 3, 3, 160, "qualified", 7, 11),
            ("call-017", 8, 8, 95,  "nurture", 4, 11),
            ("call-018", 11, 11, 310, "booked", 14, 12),
            ("call-019", 2, 2, 190, "qualified", 9, 12),
            ("call-020", 10, 10, 245, "booked", 11, 13),
        ]
        tools_map = {
            "booked": ["search_properties", "get_property_details", "check_calendar_slots", "book_site_visit"],
            "qualified": ["search_properties", "update_lead_qualification"],
            "transferred": ["search_properties", "get_property_details"],
            "nurture": ["search_properties"],
            "dropped": [],
        }
        for call_id, ci, li, dur, outcome, turns, days_ago in call_data:
            ts = now - timedelta(days=days_ago, hours=days_ago % 5, minutes=days_ago * 7 % 60)
            cid = contact_ids[ci] if ci is not None else None
            lid = lead_ids[li] if li is not None else None
            await conn.execute(
                """INSERT INTO interactions (tenant_id, contact_id, lead_id, call_id, channel, duration_seconds, outcome, created_at)
                   VALUES ($1,$2,$3,$4,'voice',$5,$6,$7)""",
                TENANT_ID, cid, lid, call_id, dur, outcome, ts,
            )
            tools = tools_map.get(outcome, [])
            await conn.execute(
                """INSERT INTO call_analytics (tenant_id, call_id, total_turns, caller_turns, agent_turns,
                   duration_seconds, tools_used, barge_in_count, outcome, lead_id, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11)""",
                TENANT_ID, call_id, turns, turns // 2, turns - turns // 2,
                dur, json.dumps(tools), max(0, turns // 5 - 1), outcome, lid, ts,
            )

            # Conversation turns for each call
            agent_lines = [
                "Good afternoon! Thank you for calling Sunrise Realty. How can I help you today?",
                "I'd be happy to help you find the right home. Let me search our available listings.",
                "I found some great options. Would you like to hear the details?",
                "Let me pull up the full property information for you.",
                "That property has excellent amenities. Would you like to schedule a visit?",
                "Let me check the available time slots for you.",
                "I've booked your site visit. You'll receive a confirmation text shortly.",
                "Is there anything else I can help you with today?",
            ]
            caller_lines = [
                "Hi, I'm looking for a home in Austin.",
                "Something with at least 3 bedrooms, under $600K if possible.",
                "Yes, tell me more about that one.",
                "Does it have a garage?",
                "Yes, I'd love to see it. What's available this week?",
                "The morning slot works for me.",
                "That's perfect, thank you!",
                "No, that's all. Thanks for your help!",
            ]
            for t in range(min(turns, 16)):
                speaker = "agent" if t % 2 == 0 else "caller"
                lines = agent_lines if speaker == "agent" else caller_lines
                text = lines[min(t // 2, len(lines) - 1)]
                await conn.execute(
                    """INSERT INTO conversation_turns (tenant_id, call_id, turn_index, speaker, text, interrupted, timestamp_ms, created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                    TENANT_ID, call_id, t, speaker, text,
                    t % 7 == 3,  # occasional interruption
                    float(t * 4500 + 1000),
                    ts + timedelta(seconds=t * 5),
                )

            # Tool invocations
            for j, tool_name in enumerate(tools):
                await conn.execute(
                    """INSERT INTO tool_invocations (tenant_id, call_id, turn_index, tool_name,
                       input_params, output_result, latency_ms, success, created_at)
                       VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8,$9)""",
                    TENANT_ID, call_id, (j + 1) * 2, tool_name,
                    json.dumps({"tenant_id": TENANT_ID}),
                    json.dumps({"status": "ok"}),
                    float(25 + j * 15),
                    True, ts + timedelta(seconds=(j + 1) * 10),
                )

        print("  Done!")
    finally:
        await conn.close()

    creds_path = Path(__file__).parent / ".dashboard-credentials"
    creds_path.write_text(
        f"TENANT_ID={TENANT_ID}\nAPI_KEY={api_key}\nDASHBOARD=http://localhost:3000\nAPI={API_BASE}\n"
    )
    print()
    print(f"Credentials saved to {creds_path}")
    print("Open http://localhost:3000 and use the tenant ID and API key from that file.")


if __name__ == "__main__":
    asyncio.run(main())
