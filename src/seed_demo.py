"""
Seed the scanner's SQLite database with realistic demo data so the
dashboard has something to render without needing live API keys.

    python src/seed_demo.py

Idempotent: safe to re-run. Wipes and re-inserts demo rows each time.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta

import aiosqlite

from scanner import C, DB  # reuse the real schema


DEMO_ROUTES = [
    # (origin, destination, dest_name, airline, normal_price_gbp)
    ("LHR", "NRT", "Tokyo Narita",       "British Airways",     820),
    ("LHR", "JFK", "New York JFK",       "Virgin Atlantic",     480),
    ("LGW", "BKK", "Bangkok",            "Thai Airways",        610),
    ("MAN", "BCN", "Barcelona",          "EasyJet",             140),
    ("LHR", "LIS", "Lisbon",             "TAP Portugal",        130),
    ("LGW", "DPS", "Bali Denpasar",      "Qatar Airways",       780),
    ("LHR", "CPT", "Cape Town",          "Virgin Atlantic",     720),
    ("LHR", "EZE", "Buenos Aires",       "Iberia",              860),
    ("LHR", "KEF", "Reykjavik",          "Icelandair",          180),
    ("LGW", "RAK", "Marrakech",          "EasyJet",             175),
    ("LHR", "ICN", "Seoul Incheon",      "Korean Air",          690),
    ("LHR", "MEX", "Mexico City",        "British Airways",     640),
    ("LGW", "ATH", "Athens",             "EasyJet",             165),
    ("LHR", "CMB", "Colombo",            "Sri Lankan Airlines", 590),
    ("LHR", "NBO", "Nairobi",            "Kenya Airways",       560),
]

DEAL_TYPES = ["error_fare", "flash_sale", "price_drop", "hidden_fare"]


async def seed():
    # Initialise schema via the real DB class.
    await DB().init()

    async with aiosqlite.connect(C.DB) as db:
        # Wipe previous demo rows — identifiable by the "demo" source/component tag.
        await db.execute("DELETE FROM prices WHERE source LIKE 'demo%'")
        await db.execute("DELETE FROM alerts WHERE fare_hash LIKE 'demo-%'")
        await db.execute("DELETE FROM scan_runs")
        await db.commit()

        now = datetime.utcnow()

        # 1. Historical price series — one scan per route per day, for 35 days.
        price_rows = []
        for origin, dest, dest_name, airline, base in DEMO_ROUTES:
            price = base
            for days_ago in range(35, 0, -1):
                # Random walk within ±20 % of base, clamped.
                price = max(base * 0.7, min(base * 1.4,
                            price + random.uniform(-0.07, 0.07) * base))
                ts = (now - timedelta(days=days_ago, hours=random.randint(0, 23))).isoformat()
                price_rows.append((
                    origin, dest, dest_name,
                    round(price, 2), "GBP",
                    airline, "ECONOMY", "1 carry-on",
                    (now + timedelta(days=random.randint(30, 180))).date().isoformat(),
                    "demo_history",
                    ts,
                ))

        await db.executemany(
            """INSERT INTO prices
               (origin, destination, dest_name, price, currency, airline, cabin,
                baggage, departure_date, source, scanned_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            price_rows,
        )

        # 2. Alerts — recent anomalies the "scanner" flagged.
        alert_rows = []
        for i, (origin, dest, dest_name, airline, base) in enumerate(DEMO_ROUTES[:12]):
            deal_type = random.choice(DEAL_TYPES)
            savings_pct = round(random.uniform(35, 70) if deal_type != "error_fare"
                                else random.uniform(70, 88), 1)
            deal_price = round(base * (1 - savings_pct / 100))
            minutes_ago = random.randint(2, 6 * 60)
            sent_at = (now - timedelta(minutes=minutes_ago)).isoformat()
            alert_rows.append((
                f"demo-{i}-{dest}",
                f"{origin}→{dest}",
                deal_price,
                deal_type,
                savings_pct,
                round(random.uniform(0.72, 0.97), 2),
                None,  # approved = pending
                sent_at,
            ))

        await db.executemany(
            """INSERT INTO alerts
               (fare_hash, route, price, deal_type, savings_pct, confidence, approved, sent_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            alert_rows,
        )

        # 3. Fake a recent scan_run so the dashboard shows a sensible scan rate.
        finished = now - timedelta(seconds=42)
        started = finished - timedelta(seconds=18)
        await db.execute(
            """INSERT INTO scan_runs
               (started_at, finished_at, duration_s, fares_scanned, anomalies, verified)
               VALUES (?,?,?,?,?,?)""",
            (started.isoformat(), finished.isoformat(), 18.0, len(price_rows), len(alert_rows), 8),
        )

        await db.commit()

        n_prices = (await (await db.execute("SELECT COUNT(*) FROM prices")).fetchone())[0]
        n_alerts = (await (await db.execute("SELECT COUNT(*) FROM alerts")).fetchone())[0]

    print(f"✅ Seeded {n_prices} price rows and {n_alerts} alerts into {C.DB}")


if __name__ == "__main__":
    asyncio.run(seed())
