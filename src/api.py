"""
FareRadar HTTP API
──────────────────
Reads the scanner's SQLite database and exposes it to the React dashboard.

    uvicorn src.api:app --reload --port 8000

Endpoints:
    GET /api/deals                       — recent alerts, newest first
    GET /api/stats                       — aggregate counters for the header
    GET /api/history?origin=&destination= — historical price series for a route
    GET /api/health                      — last health check rows

The dashboard's Vite dev server proxies /api/* to this process.
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import quote_plus

DB_PATH = os.getenv("DB_PATH", "fareradar_v2.db")

app = FastAPI(title="FareRadar API", version="0.1")

# Dashboard may run on any localhost port during dev; wide open locally.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _booking_urls(origin: str | None, destination: str | None, departure_date: str | None) -> dict:
    """Build deep-links to Google Flights and Skyscanner for a given route."""
    if not origin or not destination:
        return {"googleFlights": None, "skyscanner": None}
    depart = departure_date or ""
    # Google Flights: uses a search string in the URL.
    q = f"Flights from {origin} to {destination}"
    if depart:
        q += f" on {depart}"
    gf = f"https://www.google.com/travel/flights?q={quote_plus(q)}"
    # Skyscanner: YYMMDD in the path; omit date if we don't have one.
    if depart:
        try:
            d = datetime.fromisoformat(depart).strftime("%y%m%d")
            sk = f"https://www.skyscanner.net/transport/flights/{origin.lower()}/{destination.lower()}/{d}/"
        except ValueError:
            sk = f"https://www.skyscanner.net/transport/flights/{origin.lower()}/{destination.lower()}/"
    else:
        sk = f"https://www.skyscanner.net/transport/flights/{origin.lower()}/{destination.lower()}/"
    return {"googleFlights": gf, "skyscanner": sk}


def _conn() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise HTTPException(
            status_code=503,
            detail=f"Database {DB_PATH} does not exist yet — run the scanner or seed_demo.py first.",
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_ROUTE_RE = re.compile(r"([A-Z]{3})\s*[→\->]+\s*([A-Z]{3})")


def _split_route(route: str | None) -> tuple[str | None, str | None]:
    if not route:
        return None, None
    m = _ROUTE_RE.search(route)
    if m:
        return m.group(1), m.group(2)
    return None, None


@app.get("/api/deals")
def list_deals(limit: int = 50):
    """Return the N most recent alerts, enriched with data from the prices table."""
    with _conn() as db:
        rows = db.execute(
            """
            SELECT id, fare_hash, route, price, deal_type, savings_pct,
                   confidence, approved, sent_at
            FROM alerts
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        out = []
        now = datetime.utcnow()
        for r in rows:
            origin, destination = _split_route(r["route"])

            # Try to pull recent context (airline, cabin, normal price) for this route.
            airline = cabin = dest_name = departure_date = None
            normal_price = None
            if origin and destination:
                ctx = db.execute(
                    """
                    SELECT airline, cabin, dest_name, departure_date
                    FROM prices
                    WHERE origin=? AND destination=?
                    ORDER BY scanned_at DESC LIMIT 1
                    """,
                    (origin, destination),
                ).fetchone()
                if ctx:
                    airline, cabin, dest_name, departure_date = (
                        ctx["airline"], ctx["cabin"], ctx["dest_name"], ctx["departure_date"],
                    )
                med = db.execute(
                    """
                    SELECT AVG(price) FROM prices
                    WHERE origin=? AND destination=?
                      AND scanned_at > datetime('now', '-90 days')
                    """,
                    (origin, destination),
                ).fetchone()[0]
                if med:
                    normal_price = round(med)

            # Derive minutes-since-alert for the UI "Xm ago" label.
            try:
                sent = datetime.fromisoformat(r["sent_at"])
            except ValueError:
                sent = now
            minutes_ago = max(0, int((now - sent).total_seconds() // 60))

            savings_pct = r["savings_pct"] or 0
            if not normal_price:
                # Fallback: infer from savings_pct if we have it.
                if savings_pct > 0 and savings_pct < 100:
                    normal_price = round(r["price"] / (1 - savings_pct / 100))
                else:
                    normal_price = round(r["price"] * 1.5)

            links = _booking_urls(origin, destination, departure_date)
            out.append({
                "id": r["id"],
                "origin": origin,
                "destinationCode": destination,
                "destName": dest_name,
                "airline": airline or "Unknown",
                "cabinClass": (cabin or "Economy").title(),
                "type": r["deal_type"] or "price_drop",
                "price": round(r["price"]),
                "normalPrice": normal_price,
                "savings": round(savings_pct),
                "confidence": round((r["confidence"] or 0.75) * 100),
                "departureDate": departure_date,
                "sentAt": r["sent_at"],
                "minutesAgo": minutes_ago,
                "approved": r["approved"],
                "googleFlightsUrl": links["googleFlights"],
                "skyscannerUrl": links["skyscanner"],
            })
        return {"deals": out, "count": len(out)}


@app.post("/api/deals/{deal_id}/approve")
def approve_deal(deal_id: int):
    return _set_approval(deal_id, 1)


@app.post("/api/deals/{deal_id}/reject")
def reject_deal(deal_id: int):
    return _set_approval(deal_id, 0)


def _set_approval(deal_id: int, value: int):
    with _conn() as db:
        cur = db.execute("UPDATE alerts SET approved=? WHERE id=?", (value, deal_id))
        db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Alert {deal_id} not found")
    return {"id": deal_id, "approved": value}


@app.get("/api/stats")
def stats():
    with _conn() as db:
        today = datetime.utcnow().date().isoformat()
        fares_scanned = db.execute("SELECT COUNT(*) FROM prices").fetchone()[0]

        route_count = db.execute(
            "SELECT COUNT(DISTINCT origin || '-' || destination) FROM prices"
        ).fetchone()[0]

        deals_today = db.execute(
            "SELECT COUNT(*) FROM alerts WHERE date(sent_at)=?", (today,)
        ).fetchone()[0]

        error_fares_today = db.execute(
            "SELECT COUNT(*) FROM alerts WHERE date(sent_at)=? AND deal_type='error_fare'",
            (today,),
        ).fetchone()[0]

        avg_savings = db.execute(
            "SELECT AVG(savings_pct) FROM alerts WHERE date(sent_at)=?", (today,)
        ).fetchone()[0] or 0

        last_run = db.execute(
            "SELECT finished_at, duration_s, fares_scanned "
            "FROM scan_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    last_scan = "never"
    scan_rate = 0
    if last_run:
        try:
            delta = datetime.utcnow() - datetime.fromisoformat(last_run["finished_at"])
            secs = int(delta.total_seconds())
            if secs < 60:
                last_scan = f"{secs}s ago"
            elif secs < 3600:
                last_scan = f"{secs // 60}m ago"
            else:
                last_scan = f"{secs // 3600}h ago"
        except ValueError:
            pass
        if last_run["duration_s"] and last_run["duration_s"] > 0:
            scan_rate = round(last_run["fares_scanned"] / last_run["duration_s"])

    return {
        "routesMonitored": int(route_count),
        "faresScanned": int(fares_scanned),
        "dealsFound": int(deals_today),
        "errorFares": int(error_fares_today),
        "avgSavings": round(avg_savings),
        "lastScan": last_scan,
        "scanRate": int(scan_rate),
    }


@app.get("/api/history")
def history(origin: str, destination: str, days: int = 30):
    """Historical price series for a route, used by the detail chart."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with _conn() as db:
        rows = db.execute(
            """
            SELECT scanned_at, price FROM prices
            WHERE origin=? AND destination=? AND scanned_at > ?
            ORDER BY scanned_at ASC
            """,
            (origin, destination, cutoff),
        ).fetchall()
        if not rows:
            return {"points": [], "avg": None}

        avg = sum(r["price"] for r in rows) / len(rows)
        points = []
        for r in rows:
            try:
                d = datetime.fromisoformat(r["scanned_at"])
            except ValueError:
                continue
            points.append({
                "date": d.strftime("%d %b"),
                "price": round(r["price"]),
                "avg": round(avg),
            })
        return {"points": points, "avg": round(avg)}


@app.get("/api/health")
def health_log(limit: int = 20):
    with _conn() as db:
        rows = db.execute(
            "SELECT check_time, component, status, detail FROM health "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"checks": [dict(r) for r in rows]}


@app.get("/")
def root():
    return {"service": "fareradar-api", "endpoints": ["/api/deals", "/api/stats", "/api/history", "/api/health"]}
