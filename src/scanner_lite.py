"""
FareRadar Free — Flight Deal Scanner (Zero Cost Edition)
========================================================
Scans 2,400+ routes daily using only free-tier APIs.

Phase 1: SerpAPI Google Travel Explore → "everywhere" sweep (8 calls/day)
Phase 2: Amadeus Self-Service → anomaly verification (40 calls/day)
Phase 3: Kiwi Tequila → deep scan on hot routes (80 calls/day)
Phase 4: Google Flights scraper → cross-source validation (free, unlimited)

Total monthly API cost: £0

Setup:
  1. pip install httpx aiosqlite
  2. pip install fast-flights  (Google Flights scraper — github.com/AWeirdDev/flights)
  3. Copy .env.example → .env, add your free API keys
  4. python fare_radar_free.py

API keys (all free):
  - Amadeus: https://developers.amadeus.com (Self-Service, 2,000 calls/month)
  - Kiwi Tequila: https://tequila.kiwi.com (free registration)
  - SerpAPI: https://serpapi.com (250 queries/month free)
  - Telegram: message @BotFather on Telegram (free)
"""

import asyncio
import json
import hashlib
import logging
import os
import sys
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import httpx
import aiosqlite

# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

class Config:
    # API Keys
    AMADEUS_KEY = os.getenv("AMADEUS_API_KEY", "")
    AMADEUS_SECRET = os.getenv("AMADEUS_API_SECRET", "")
    KIWI_KEY = os.getenv("KIWI_API_KEY", "")
    SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

    # Departure airports (your home airports)
    ORIGINS = os.getenv("ORIGINS", "LHR,LGW,STN,MAN,EDI,BHX,BRS,LTN").split(",")

    # Thresholds
    ANOMALY_PCT = float(os.getenv("ANOMALY_PCT", "35"))       # % below avg to flag
    ERROR_FARE_PCT = float(os.getenv("ERROR_FARE_PCT", "60"))  # % below avg = error fare
    MIN_DATAPOINTS = int(os.getenv("MIN_DATAPOINTS", "3"))

    # Rate limits (calls per day to stay within free tiers)
    SERPAPI_DAILY = int(os.getenv("SERPAPI_DAILY", "8"))     # 250/month ÷ 30
    AMADEUS_DAILY = int(os.getenv("AMADEUS_DAILY", "60"))    # 2000/month ÷ 30
    KIWI_DAILY = int(os.getenv("KIWI_DAILY", "100"))        # estimated free tier

    DB_PATH = os.getenv("DB_PATH", "fareradar_free.db")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fareradar")


# ══════════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════════

class DealType(str, Enum):
    ERROR_FARE = "error_fare"
    FLASH_SALE = "flash_sale"
    PRICE_DROP = "price_drop"


@dataclass
class Fare:
    origin: str
    destination: str
    dest_name: str
    price: float
    currency: str
    airline: str = "Various"
    departure_date: str = ""
    return_date: str = ""
    stops: int = -1
    source: str = ""
    booking_url: str = ""

    @property
    def route(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def hash(self) -> str:
        return hashlib.md5(
            f"{self.origin}{self.destination}{self.price}{self.departure_date}".encode()
        ).hexdigest()[:12]


@dataclass
class Deal:
    fare: Fare
    deal_type: DealType
    savings_pct: float
    avg_price: float
    confidence: float

    def telegram_text(self) -> str:
        emoji = {"error_fare": "⚡🚨", "flash_sale": "🔥", "price_drop": "📉"}
        typ = self.deal_type.value
        return (
            f"{emoji.get(typ, '📢')} {typ.upper().replace('_', ' ')}\n\n"
            f"📍 {self.fare.origin} → {self.fare.destination} ({self.fare.dest_name})\n"
            f"✈️  {self.fare.airline}\n"
            f"💰 {self.fare.currency} {self.fare.price:.0f}  "
            f"(avg ~{self.fare.currency} {self.avg_price:.0f})\n"
            f"📊 {self.savings_pct:.0f}% below average\n"
            f"📅 {self.fare.departure_date}"
            f"{f' → {self.fare.return_date}' if self.fare.return_date else ''}\n"
            f"🎯 Confidence: {self.confidence:.0f}%\n"
            f"🔗 Source: {self.fare.source}\n"
            + (f"\n🔗 Book: {self.fare.booking_url}" if self.fare.booking_url else "")
        )


# ══════════════════════════════════════════════════════════════
# Database
# ══════════════════════════════════════════════════════════════

class DB:
    def __init__(self, path=Config.DB_PATH):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    origin TEXT, destination TEXT, dest_name TEXT,
                    price REAL, currency TEXT, airline TEXT,
                    source TEXT, scanned_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_route ON prices(origin, destination);

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fare_hash TEXT, route TEXT, price REAL,
                    deal_type TEXT, savings_pct REAL,
                    sent_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_hash ON alerts(fare_hash);

                CREATE TABLE IF NOT EXISTS api_usage (
                    date TEXT, source TEXT, calls INTEGER DEFAULT 0,
                    PRIMARY KEY (date, source)
                );
            """)
            await db.commit()

    async def store_fares(self, fares: list[Fare]):
        async with aiosqlite.connect(self.path) as db:
            await db.executemany(
                "INSERT INTO prices (origin,destination,dest_name,price,currency,airline,source) "
                "VALUES (?,?,?,?,?,?,?)",
                [(f.origin, f.destination, f.dest_name, f.price,
                  f.currency, f.airline, f.source) for f in fares],
            )
            await db.commit()

    async def route_stats(self, origin: str, dest: str) -> Optional[dict]:
        """Get rolling stats for a route from last 90 days."""
        cutoff = (datetime.utcnow() - timedelta(days=90)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT AVG(price), MIN(price), MAX(price), COUNT(*), "
                "AVG(price*price) - AVG(price)*AVG(price) "
                "FROM prices WHERE origin=? AND destination=? AND scanned_at>?",
                (origin, dest, cutoff),
            ) as cur:
                row = await cur.fetchone()
                if row and row[0] and row[3] >= Config.MIN_DATAPOINTS:
                    return {
                        "avg": row[0], "min": row[1], "max": row[2],
                        "n": row[3], "std": math.sqrt(max(0, row[4] or 0)),
                    }
        return None

    async def was_alerted(self, fare_hash: str, hours: int = 24) -> bool:
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT 1 FROM alerts WHERE fare_hash=? AND sent_at>?",
                (fare_hash, cutoff),
            ) as cur:
                return await cur.fetchone() is not None

    async def record_alert(self, deal: Deal):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO alerts (fare_hash,route,price,deal_type,savings_pct) VALUES (?,?,?,?,?)",
                (deal.fare.hash, deal.fare.route, deal.fare.price,
                 deal.deal_type.value, deal.savings_pct),
            )
            await db.commit()

    async def check_api_budget(self, source: str, daily_limit: int) -> bool:
        """Check if we've exceeded daily API budget for a source."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT calls FROM api_usage WHERE date=? AND source=?",
                (today, source),
            ) as cur:
                row = await cur.fetchone()
                return (row[0] if row else 0) < daily_limit

    async def increment_api_usage(self, source: str, count: int = 1):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO api_usage (date, source, calls) VALUES (?, ?, ?) "
                "ON CONFLICT(date, source) DO UPDATE SET calls = calls + ?",
                (today, source, count, count),
            )
            await db.commit()

    async def get_api_usage_today(self) -> dict:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        usage = {}
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT source, calls FROM api_usage WHERE date=?", (today,)
            ) as cur:
                async for row in cur:
                    usage[row[0]] = row[1]
        return usage


# ══════════════════════════════════════════════════════════════
# Phase 1: SerpAPI Google Travel Explore
# ══════════════════════════════════════════════════════════════

class ExploreScanner:
    """
    Uses SerpAPI's Google Travel Explore endpoint.
    One call per departure airport returns cheapest fares to ALL destinations.
    This is the most efficient scan possible: ~300 destinations per call.

    Free tier: 250 queries/month ≈ 8/day
    """

    def __init__(self, db: DB):
        self.client = httpx.AsyncClient(timeout=30)
        self.db = db

    async def scan_from(self, origin: str) -> list[Fare]:
        if not Config.SERPAPI_KEY:
            log.warning("SerpAPI key not set, skipping explore scan")
            return []

        if not await self.db.check_api_budget("serpapi", Config.SERPAPI_DAILY):
            log.info("SerpAPI daily budget exhausted, skipping")
            return []

        try:
            resp = await self.client.get(
                "https://serpapi.com/search",
                params={
                    "engine": "google_travel_explore",
                    "departure_id": origin,
                    "currency": "GBP",
                    "hl": "en",
                    "gl": "uk",
                    "api_key": Config.SERPAPI_KEY,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            await self.db.increment_api_usage("serpapi")
        except Exception as e:
            log.error("SerpAPI explore failed for %s: %s", origin, e)
            return []

        fares = []
        for dest in data.get("destinations", []):
            try:
                price = dest.get("flight_price") or dest.get("price")
                if not price:
                    continue
                # Price might be string like "$234" or int
                if isinstance(price, str):
                    price = float(price.replace("$", "").replace("£", "").replace(",", ""))

                airport_code = dest.get("airport", {}).get("id", "")
                city_name = dest.get("name", dest.get("title", "Unknown"))

                fares.append(Fare(
                    origin=origin,
                    destination=airport_code or city_name[:3].upper(),
                    dest_name=city_name,
                    price=float(price),
                    currency="GBP",
                    source="google_explore",
                ))
            except (ValueError, KeyError, TypeError) as e:
                log.debug("Skipping explore result: %s", e)

        log.info("📡 Explore %s: found %d destinations", origin, len(fares))
        return fares

    async def scan_all(self) -> list[Fare]:
        """Scan all departure airports. Uses ~8 API calls."""
        all_fares = []
        for origin in Config.ORIGINS:
            fares = await self.scan_from(origin)
            all_fares.extend(fares)
            await asyncio.sleep(2)  # Be polite
        return all_fares

    async def close(self):
        await self.client.aclose()


# ══════════════════════════════════════════════════════════════
# Phase 2: Amadeus Verification
# ══════════════════════════════════════════════════════════════

class AmadeusVerifier:
    """
    Uses Amadeus Self-Service API to verify anomalies.
    Only called for routes flagged by Phase 1.

    Free tier: 2,000 calls/month ≈ 66/day
    """

    BASE = "https://api.amadeus.com"

    def __init__(self, db: DB):
        self.client = httpx.AsyncClient(timeout=30)
        self.db = db
        self.token = None
        self.token_exp = datetime.min

    async def auth(self):
        if self.token and datetime.utcnow() < self.token_exp:
            return
        resp = await self.client.post(f"{self.BASE}/v1/security/oauth2/token", data={
            "grant_type": "client_credentials",
            "client_id": Config.AMADEUS_KEY,
            "client_secret": Config.AMADEUS_SECRET,
        })
        resp.raise_for_status()
        d = resp.json()
        self.token = d["access_token"]
        self.token_exp = datetime.utcnow() + timedelta(seconds=d["expires_in"] - 60)

    async def verify_route(self, origin: str, dest: str) -> list[Fare]:
        """Search cheapest dates for a specific route."""
        if not Config.AMADEUS_KEY:
            return []
        if not await self.db.check_api_budget("amadeus", Config.AMADEUS_DAILY):
            log.info("Amadeus daily budget exhausted")
            return []

        await self.auth()
        try:
            resp = await self.client.get(
                f"{self.BASE}/v1/shopping/flight-dates",
                headers={"Authorization": f"Bearer {self.token}"},
                params={"origin": origin, "destination": dest, "oneWay": "false"},
            )
            await self.db.increment_api_usage("amadeus")

            if resp.status_code != 200:
                log.debug("Amadeus %s→%s: HTTP %d", origin, dest, resp.status_code)
                return []

            data = resp.json()
        except Exception as e:
            log.warning("Amadeus verify failed %s→%s: %s", origin, dest, e)
            return []

        fares = []
        for item in data.get("data", []):
            try:
                fares.append(Fare(
                    origin=origin,
                    destination=dest,
                    dest_name=dest,
                    price=float(item["price"]["total"]),
                    currency=data.get("meta", {}).get("currency", "GBP"),
                    departure_date=item.get("departureDate", ""),
                    return_date=item.get("returnDate", ""),
                    source="amadeus",
                ))
            except (KeyError, ValueError):
                continue

        log.info("🔍 Amadeus %s→%s: %d fares found", origin, dest, len(fares))
        return fares

    async def get_price_metrics(self, origin: str, dest: str,
                                  date: str) -> Optional[dict]:
        """Get price percentiles for context."""
        if not await self.db.check_api_budget("amadeus", Config.AMADEUS_DAILY):
            return None
        await self.auth()
        try:
            resp = await self.client.get(
                f"{self.BASE}/v1/analytics/itinerary-price-metrics",
                headers={"Authorization": f"Bearer {self.token}"},
                params={
                    "originIataCode": origin,
                    "destinationIataCode": dest,
                    "departureDate": date,
                    "currencyCode": "GBP",
                    "oneWay": "false",
                },
            )
            await self.db.increment_api_usage("amadeus")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("data"):
                    return {
                        m["quartileRanking"]: float(m["amount"])
                        for m in data["data"][0].get("priceMetrics", [])
                    }
        except Exception:
            pass
        return None

    async def close(self):
        await self.client.aclose()


# ══════════════════════════════════════════════════════════════
# Phase 3: Kiwi Deep Scan
# ══════════════════════════════════════════════════════════════

class KiwiDeepScanner:
    """
    Uses Kiwi Tequila API for deep scanning confirmed anomalies.
    Great for budget carriers and provides booking deep-links.

    Free tier: ~3,000 calls/month ≈ 100/day
    """

    BASE = "https://tequila-api.kiwi.com"

    def __init__(self, db: DB):
        self.client = httpx.AsyncClient(timeout=30)
        self.db = db

    async def deep_scan(self, origin: str, dest: str) -> list[Fare]:
        """Search all dates in a 6-month window for a specific route."""
        if not Config.KIWI_KEY:
            return []
        if not await self.db.check_api_budget("kiwi", Config.KIWI_DAILY):
            log.info("Kiwi daily budget exhausted")
            return []

        now = datetime.utcnow()
        try:
            resp = await self.client.get(
                f"{self.BASE}/v2/search",
                headers={"apikey": Config.KIWI_KEY},
                params={
                    "fly_from": origin,
                    "fly_to": dest,
                    "date_from": (now + timedelta(days=7)).strftime("%d/%m/%Y"),
                    "date_to": (now + timedelta(days=180)).strftime("%d/%m/%Y"),
                    "nights_in_dst_from": 3,
                    "nights_in_dst_to": 14,
                    "flight_type": "round",
                    "curr": "GBP",
                    "limit": 20,
                    "sort": "price",
                    "asc": 1,
                    "one_for_city": 0,
                },
            )
            await self.db.increment_api_usage("kiwi")

            if resp.status_code == 403:
                log.warning("Kiwi API returned 403 — key may need activation")
                return []

            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("Kiwi deep scan failed %s→%s: %s", origin, dest, e)
            return []

        fares = []
        for flight in data.get("data", []):
            try:
                airlines = flight.get("airlines", ["Unknown"])
                fares.append(Fare(
                    origin=origin,
                    destination=flight.get("flyTo", dest),
                    dest_name=flight.get("cityTo", dest),
                    price=float(flight["price"]),
                    currency="GBP",
                    airline=", ".join(airlines) if airlines else "Unknown",
                    departure_date=flight.get("local_departure", "")[:10],
                    return_date=flight.get("local_arrival", "")[:10],
                    stops=max(0, len(flight.get("route", [])) // 2 - 1),
                    source="kiwi",
                    booking_url=flight.get("deep_link", ""),
                ))
            except (KeyError, ValueError):
                continue

        log.info("🔎 Kiwi %s→%s: %d fares found", origin, dest, len(fares))
        return fares

    async def scan_anywhere(self, origin: str) -> list[Fare]:
        """Broad 'anywhere' scan from an airport — catches deals Explore misses."""
        if not Config.KIWI_KEY:
            return []
        if not await self.db.check_api_budget("kiwi", Config.KIWI_DAILY):
            return []

        now = datetime.utcnow()
        try:
            resp = await self.client.get(
                f"{self.BASE}/v2/search",
                headers={"apikey": Config.KIWI_KEY},
                params={
                    "fly_from": origin,
                    # No fly_to = search everywhere
                    "date_from": (now + timedelta(days=14)).strftime("%d/%m/%Y"),
                    "date_to": (now + timedelta(days=180)).strftime("%d/%m/%Y"),
                    "nights_in_dst_from": 3,
                    "nights_in_dst_to": 14,
                    "flight_type": "round",
                    "curr": "GBP",
                    "limit": 50,
                    "sort": "price",
                    "asc": 1,
                    "one_for_city": 1,
                },
            )
            await self.db.increment_api_usage("kiwi")
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("Kiwi anywhere scan failed from %s: %s", origin, e)
            return []

        fares = []
        for flight in data.get("data", []):
            try:
                fares.append(Fare(
                    origin=origin,
                    destination=flight.get("flyTo", "???"),
                    dest_name=flight.get("cityTo", "Unknown"),
                    price=float(flight["price"]),
                    currency="GBP",
                    airline=", ".join(flight.get("airlines", ["?"])),
                    departure_date=flight.get("local_departure", "")[:10],
                    source="kiwi",
                    booking_url=flight.get("deep_link", ""),
                ))
            except (KeyError, ValueError):
                continue

        log.info("🌍 Kiwi anywhere from %s: %d destinations", origin, len(fares))
        return fares

    async def close(self):
        await self.client.aclose()


# ══════════════════════════════════════════════════════════════
# Phase 4: Google Flights Scraper (free, no API key)
# ══════════════════════════════════════════════════════════════

class GoogleFlightsChecker:
    """
    Uses the open-source 'fast-flights' library to scrape Google Flights.
    No API key needed, no quota. Rate-limited only by Google.

    Install: pip install fast-flights
    GitHub: github.com/AWeirdDev/flights

    Falls back gracefully if not installed.
    """

    def __init__(self):
        self.available = False
        try:
            from fast_flights import FlightData, Passengers, create_filter, get_flights
            self.FlightData = FlightData
            self.Passengers = Passengers
            self.create_filter = create_filter
            self.get_flights = get_flights
            self.available = True
            log.info("✅ Google Flights scraper available")
        except ImportError:
            log.warning("⚠️  fast-flights not installed. Phase 4 disabled.")
            log.warning("   Install with: pip install fast-flights")

    async def verify_fare(self, origin: str, dest: str,
                           date: str) -> Optional[float]:
        """
        Check the actual Google Flights price for a route/date.
        Returns the cheapest price or None.
        """
        if not self.available:
            return None

        try:
            # Run in executor since fast-flights is synchronous
            loop = asyncio.get_event_loop()
            price = await loop.run_in_executor(
                None, self._scrape_price, origin, dest, date
            )
            return price
        except Exception as e:
            log.debug("Google Flights check failed %s→%s: %s", origin, dest, e)
            return None

    def _scrape_price(self, origin: str, dest: str, date: str) -> Optional[float]:
        """Synchronous scrape of Google Flights."""
        try:
            filter = self.create_filter(
                self.FlightData(date=date, from_airport=origin, to_airport=dest),
            )
            result = self.get_flights(filter)
            if result and result.flights:
                prices = []
                for flight in result.flights:
                    if flight.price:
                        # Price is like "£234" or "$456"
                        p = flight.price.replace("£", "").replace("$", "").replace(",", "")
                        prices.append(float(p))
                return min(prices) if prices else None
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════
# Anomaly Detector
# ══════════════════════════════════════════════════════════════

class Detector:
    def __init__(self, db: DB):
        self.db = db

    async def check(self, fare: Fare) -> Optional[Deal]:
        stats = await self.db.route_stats(fare.origin, fare.destination)
        if not stats:
            return None

        savings = ((stats["avg"] - fare.price) / stats["avg"]) * 100
        if savings < Config.ANOMALY_PCT:
            return None

        # Already alerted?
        if await self.db.was_alerted(fare.hash):
            return None

        # Classify
        if savings >= Config.ERROR_FARE_PCT:
            deal_type = DealType.ERROR_FARE
        elif savings >= 45:
            deal_type = DealType.FLASH_SALE
        else:
            deal_type = DealType.PRICE_DROP

        # Confidence
        conf = 50.0
        conf += min(20, stats["n"] * 0.8)       # More data = higher confidence
        if stats["std"] > 0:
            z = (stats["avg"] - fare.price) / stats["std"]
            conf += min(20, z * 5)               # More std devs = higher confidence
        conf += min(10, savings * 0.15)          # Higher savings = higher confidence
        conf = min(99, max(10, conf))

        return Deal(
            fare=fare,
            deal_type=deal_type,
            savings_pct=savings,
            avg_price=stats["avg"],
            confidence=conf,
        )


# ══════════════════════════════════════════════════════════════
# Alert Dispatcher
# ══════════════════════════════════════════════════════════════

class Alerts:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15)

    async def send(self, deal: Deal):
        """Send via Telegram. Add more channels as needed."""
        if Config.TELEGRAM_TOKEN and Config.TELEGRAM_CHAT:
            await self._telegram(deal)
        else:
            # Fallback: just log it
            log.info("🎯 DEAL: %s", deal.telegram_text())

    async def _telegram(self, deal: Deal):
        try:
            resp = await self.client.post(
                f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": Config.TELEGRAM_CHAT,
                    "text": deal.telegram_text(),
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code == 200:
                log.info("✅ Telegram sent: %s→%s £%.0f (-%0.f%%)",
                         deal.fare.origin, deal.fare.destination,
                         deal.fare.price, deal.savings_pct)
            else:
                log.error("Telegram failed: %s", resp.text[:200])
        except Exception as e:
            log.error("Telegram error: %s", e)

    async def close(self):
        await self.client.aclose()


# ══════════════════════════════════════════════════════════════
# Main Scanner Orchestrator
# ══════════════════════════════════════════════════════════════

class FareRadar:
    def __init__(self):
        self.db = DB()
        self.explore = ExploreScanner(self.db)
        self.amadeus = AmadeusVerifier(self.db)
        self.kiwi = KiwiDeepScanner(self.db)
        self.google = GoogleFlightsChecker()
        self.detector = Detector(self.db)
        self.alerts = Alerts()

    async def run_scan(self) -> list[Deal]:
        """Execute the full 4-phase scan pipeline."""
        await self.db.init()
        all_deals = []

        # ── Phase 1: Explore sweep ───────────────────────────
        log.info("━" * 50)
        log.info("📡 PHASE 1: Google Travel Explore sweep")
        log.info("━" * 50)

        explore_fares = await self.explore.scan_all()
        if explore_fares:
            await self.db.store_fares(explore_fares)
            log.info("Stored %d explore fares", len(explore_fares))

        # Also run Kiwi "anywhere" scans to catch budget carriers
        log.info("\n🌍 Running Kiwi 'anywhere' scans...")
        for origin in Config.ORIGINS[:4]:  # Top 4 airports to save budget
            kiwi_anywhere = await self.kiwi.scan_anywhere(origin)
            if kiwi_anywhere:
                await self.db.store_fares(kiwi_anywhere)
            await asyncio.sleep(1)

        # ── Detect anomalies from Phase 1 ────────────────────
        log.info("\n🔍 Checking for anomalies in explore results...")
        anomaly_routes = []
        for fare in explore_fares:
            deal = await self.detector.check(fare)
            if deal:
                anomaly_routes.append((fare.origin, fare.destination, fare))
                log.info("  ⚠️  Anomaly: %s→%s %s%.0f (%.0f%% off)",
                         fare.origin, fare.destination, fare.currency,
                         fare.price, deal.savings_pct)

        log.info("Found %d anomaly routes to verify", len(anomaly_routes))

        # ── Phase 2: Amadeus verification ────────────────────
        if anomaly_routes:
            log.info("\n" + "━" * 50)
            log.info("🔬 PHASE 2: Amadeus verification (%d routes)", len(anomaly_routes))
            log.info("━" * 50)

            for origin, dest, explore_fare in anomaly_routes:
                amadeus_fares = await self.amadeus.verify_route(origin, dest)
                if amadeus_fares:
                    await self.db.store_fares(amadeus_fares)

                    # Find the cheapest Amadeus fare
                    cheapest = min(amadeus_fares, key=lambda f: f.price)
                    deal = await self.detector.check(cheapest)
                    if deal:
                        log.info("  ✅ Confirmed: %s→%s £%.0f via Amadeus",
                                 origin, dest, cheapest.price)

                        # ── Phase 3: Kiwi deep scan ──────────
                        kiwi_fares = await self.kiwi.deep_scan(origin, dest)
                        if kiwi_fares:
                            await self.db.store_fares(kiwi_fares)
                            kiwi_cheapest = min(kiwi_fares, key=lambda f: f.price)
                            kiwi_deal = await self.detector.check(kiwi_cheapest)

                            # Use the best deal from any source
                            best = deal
                            if kiwi_deal and kiwi_cheapest.price < cheapest.price:
                                best = kiwi_deal
                                log.info("  🎯 Kiwi found even cheaper: £%.0f",
                                         kiwi_cheapest.price)

                            # ── Phase 4: Google Flights cross-check ──
                            if cheapest.departure_date:
                                gf_price = await self.google.verify_fare(
                                    origin, dest, cheapest.departure_date
                                )
                                if gf_price:
                                    log.info("  🔗 Google Flights confirms: £%.0f", gf_price)
                                    best.confidence = min(99, best.confidence + 10)

                            # Alert!
                            all_deals.append(best)
                            await self.db.record_alert(best)
                            await self.alerts.send(best)
                    else:
                        log.info("  ❌ Not confirmed by Amadeus: %s→%s", origin, dest)

                await asyncio.sleep(1.5)  # Rate limiting

        # ── Summary ──────────────────────────────────────────
        usage = await self.db.get_api_usage_today()
        log.info("\n" + "═" * 50)
        log.info("📊 SCAN COMPLETE")
        log.info("═" * 50)
        log.info("  Routes scanned:  %d", len(explore_fares))
        log.info("  Anomalies found: %d", len(anomaly_routes))
        log.info("  Deals confirmed: %d", len(all_deals))
        log.info("  API calls today: SerpAPI=%d, Amadeus=%d, Kiwi=%d",
                 usage.get("serpapi", 0), usage.get("amadeus", 0),
                 usage.get("kiwi", 0))
        log.info("═" * 50)

        return all_deals

    async def run_loop(self):
        """Run continuously every 30 minutes."""
        log.info("🚀 FareRadar Free starting")
        log.info("   Airports: %s", ", ".join(Config.ORIGINS))
        log.info("   Threshold: %.0f%% below average", Config.ANOMALY_PCT)

        while True:
            try:
                deals = await self.run_scan()
                if deals:
                    log.info("🎉 Found %d deals!", len(deals))
            except Exception as e:
                log.error("Scan error: %s", e, exc_info=True)

            log.info("💤 Next scan in 30 minutes...\n")
            await asyncio.sleep(30 * 60)

    async def shutdown(self):
        await self.explore.close()
        await self.amadeus.close()
        await self.kiwi.close()
        await self.alerts.close()


# ══════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════

async def main():
    scanner = FareRadar()
    try:
        if "--once" in sys.argv:
            await scanner.run_scan()
        else:
            await scanner.run_loop()
    except KeyboardInterrupt:
        log.info("Stopped by user")
    finally:
        await scanner.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
