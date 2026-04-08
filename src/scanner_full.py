"""
FareRadar — Autonomous Fare Intelligence Engine
================================================
A production-grade flight deal scanner that monitors millions of fare routes,
detects anomalies (error fares, flash sales, price drops), and dispatches
alerts via multiple channels.

Architecture:
  Scanner → Normalizer → Anomaly Detector → Alert Dispatcher
     ↕            ↕              ↕                 ↕
  Fare APIs    Price DB     ML Scoring         Telegram/Email/Push

Requirements:
  pip install httpx aiohttp aiosqlite python-telegram-bot sendgrid apscheduler pydantic

Usage:
  python fare_radar.py                  # Run the scanner loop
  python fare_radar.py --backfill       # Backfill historical prices
  python fare_radar.py --scan-once      # Single scan pass (for cron)
"""

import asyncio
import json
import hashlib
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from pathlib import Path

import httpx
import aiosqlite
from pydantic import BaseModel

# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

class Config:
    """Central configuration — override via environment variables."""

    # API Keys (set these as environment variables)
    AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY", "")
    AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET", "")
    KIWI_API_KEY = os.getenv("KIWI_API_KEY", "")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
    ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")

    # Scanner settings
    DB_PATH = os.getenv("DB_PATH", "fareradar.db")
    SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))
    ANOMALY_THRESHOLD_PCT = float(os.getenv("ANOMALY_THRESHOLD_PCT", "40"))  # % below average
    ERROR_FARE_THRESHOLD_PCT = float(os.getenv("ERROR_FARE_THRESHOLD_PCT", "65"))
    MIN_HISTORICAL_DATAPOINTS = int(os.getenv("MIN_DATAPOINTS", "5"))
    PRICE_HISTORY_DAYS = int(os.getenv("PRICE_HISTORY_DAYS", "90"))

    # Departure airports to monitor (IATA codes)
    DEPARTURE_AIRPORTS = os.getenv(
        "DEPARTURE_AIRPORTS",
        "LHR,LGW,STN,MAN,EDI,BHX,LTN,BRS"
    ).split(",")

    # How far ahead to search (months)
    SEARCH_WINDOW_MONTHS = int(os.getenv("SEARCH_WINDOW_MONTHS", "6"))

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fareradar")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

class DealType(str, Enum):
    ERROR_FARE = "error_fare"
    FLASH_SALE = "flash_sale"
    PRICE_DROP = "price_drop"
    HIDDEN_FARE = "hidden_fare"


class CabinClass(str, Enum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


@dataclass
class FareResult:
    """A single fare returned from an API source."""
    origin: str
    destination: str
    airline: str
    price: float
    currency: str
    departure_date: str
    return_date: Optional[str]
    cabin_class: CabinClass
    stops: int
    source: str  # Which API/source found it
    booking_url: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    @property
    def route_key(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def fare_hash(self) -> str:
        key = f"{self.origin}{self.destination}{self.airline}{self.price}{self.departure_date}"
        return hashlib.md5(key.encode()).hexdigest()[:12]


@dataclass
class Deal:
    """A detected anomaly / deal worth alerting on."""
    fare: FareResult
    deal_type: DealType
    savings_pct: float
    avg_price: float
    min_price: float
    confidence: float  # 0-100
    expires_estimate: Optional[str] = None
    analysis: str = ""

    def to_alert_text(self) -> str:
        emoji = {
            DealType.ERROR_FARE: "⚡🚨",
            DealType.FLASH_SALE: "🔥",
            DealType.PRICE_DROP: "📉",
            DealType.HIDDEN_FARE: "🔍",
        }[self.deal_type]

        return (
            f"{emoji} {self.deal_type.value.upper().replace('_', ' ')}\n"
            f"\n"
            f"{'━' * 32}\n"
            f"📍 {self.fare.origin} → {self.fare.destination}\n"
            f"✈️  {self.fare.airline}\n"
            f"💰 {self.fare.currency} {self.fare.price:.0f}  (normally ~{self.fare.currency} {self.avg_price:.0f})\n"
            f"📊 {self.savings_pct:.0f}% below average\n"
            f"📅 {self.fare.departure_date}"
            f"{f' → {self.fare.return_date}' if self.fare.return_date else ''}\n"
            f"🎫 {self.fare.cabin_class.value.title()} · "
            f"{'Direct' if self.fare.stops == 0 else f'{self.fare.stops} stop(s)'}\n"
            f"🎯 Confidence: {self.confidence:.0f}%\n"
            f"{'━' * 32}\n"
            f"\n"
            f"{self.analysis}\n"
            f"\n"
            f"⏰ Act fast — {self.expires_estimate or 'unknown lifespan'}"
        )


# ══════════════════════════════════════════════════════════════
# Database Layer
# ══════════════════════════════════════════════════════════════

class PriceDatabase:
    """SQLite-backed price history and deal tracking."""

    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path

    async def initialize(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    airline TEXT,
                    price REAL NOT NULL,
                    currency TEXT DEFAULT 'GBP',
                    cabin_class TEXT DEFAULT 'economy',
                    stops INTEGER DEFAULT 0,
                    departure_date TEXT,
                    source TEXT,
                    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fare_hash TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_route
                    ON price_history(origin, destination);
                CREATE INDEX IF NOT EXISTS idx_scanned
                    ON price_history(scanned_at);
                CREATE INDEX IF NOT EXISTS idx_fare_hash
                    ON price_history(fare_hash);

                CREATE TABLE IF NOT EXISTS deals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fare_hash TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    airline TEXT,
                    price REAL NOT NULL,
                    avg_price REAL,
                    savings_pct REAL,
                    deal_type TEXT,
                    confidence REAL,
                    alerted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'active'
                );

                CREATE INDEX IF NOT EXISTS idx_deals_hash
                    ON deals(fare_hash);

                CREATE TABLE IF NOT EXISTS scan_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_started TIMESTAMP,
                    scan_finished TIMESTAMP,
                    routes_scanned INTEGER DEFAULT 0,
                    fares_found INTEGER DEFAULT 0,
                    deals_detected INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0
                );
            """)
            await db.commit()
            logger.info("Database initialized: %s", self.db_path)

    async def store_fare(self, fare: FareResult):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO price_history
                   (origin, destination, airline, price, currency, cabin_class,
                    stops, departure_date, source, fare_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fare.origin, fare.destination, fare.airline, fare.price,
                 fare.currency, fare.cabin_class.value, fare.stops,
                 fare.departure_date, fare.source, fare.fare_hash),
            )
            await db.commit()

    async def store_fares_batch(self, fares: list[FareResult]):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(
                """INSERT INTO price_history
                   (origin, destination, airline, price, currency, cabin_class,
                    stops, departure_date, source, fare_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(f.origin, f.destination, f.airline, f.price, f.currency,
                  f.cabin_class.value, f.stops, f.departure_date, f.source,
                  f.fare_hash) for f in fares],
            )
            await db.commit()

    async def get_route_stats(self, origin: str, destination: str,
                               days: int = 90) -> dict:
        """Get price statistics for a route over the past N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT
                     AVG(price) as avg_price,
                     MIN(price) as min_price,
                     MAX(price) as max_price,
                     COUNT(*) as datapoints,
                     -- Standard deviation approximation
                     AVG(price * price) - AVG(price) * AVG(price) as variance
                   FROM price_history
                   WHERE origin = ? AND destination = ?
                     AND scanned_at > ?
                     AND cabin_class = 'economy'""",
                (origin, destination, cutoff),
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    import math
                    variance = max(0, row[4] or 0)
                    return {
                        "avg_price": row[0],
                        "min_price": row[1],
                        "max_price": row[2],
                        "datapoints": row[3],
                        "std_dev": math.sqrt(variance),
                    }
                return None

    async def is_already_alerted(self, fare_hash: str, hours: int = 24) -> bool:
        """Check if we've already sent an alert for this fare recently."""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM deals WHERE fare_hash = ? AND alerted_at > ?",
                (fare_hash, cutoff),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] > 0

    async def store_deal(self, deal: Deal):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO deals
                   (fare_hash, origin, destination, airline, price,
                    avg_price, savings_pct, deal_type, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (deal.fare.fare_hash, deal.fare.origin, deal.fare.destination,
                 deal.fare.airline, deal.fare.price, deal.avg_price,
                 deal.savings_pct, deal.deal_type.value, deal.confidence),
            )
            await db.commit()

    async def log_scan(self, started, finished, routes, fares, deals, errors):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO scan_log
                   (scan_started, scan_finished, routes_scanned,
                    fares_found, deals_detected, errors)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (started.isoformat(), finished.isoformat(),
                 routes, fares, deals, errors),
            )
            await db.commit()


# ══════════════════════════════════════════════════════════════
# Fare Sources (API Adapters)
# ══════════════════════════════════════════════════════════════

class AmadeusSource:
    """
    Amadeus Self-Service API adapter.
    Free tier: 2,000 calls/month.
    Docs: https://developers.amadeus.com
    """
    BASE_URL = "https://api.amadeus.com"
    TOKEN_URL = f"{BASE_URL}/v1/security/oauth2/token"

    def __init__(self):
        self.api_key = Config.AMADEUS_API_KEY
        self.api_secret = Config.AMADEUS_API_SECRET
        self.access_token = None
        self.token_expires = datetime.min
        self.client = httpx.AsyncClient(timeout=30)

    async def authenticate(self):
        if self.access_token and datetime.utcnow() < self.token_expires:
            return
        resp = await self.client.post(self.TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.api_secret,
        })
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self.token_expires = datetime.utcnow() + timedelta(seconds=data["expires_in"] - 60)
        logger.debug("Amadeus token refreshed")

    async def search_flights(self, origin: str, destination: str,
                              departure_date: str,
                              return_date: str = None) -> list[FareResult]:
        """Search for flight offers on a specific route/date."""
        await self.authenticate()

        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date,
            "adults": 1,
            "nonStop": "false",
            "currencyCode": "GBP",
            "max": 10,
        }
        if return_date:
            params["returnDate"] = return_date

        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/v2/shopping/flight-offers",
                headers={"Authorization": f"Bearer {self.access_token}"},
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Amadeus search failed %s→%s: %s", origin, destination, e)
            return []

        fares = []
        for offer in data.get("data", []):
            try:
                price = float(offer["price"]["grandTotal"])
                segments = offer["itineraries"][0]["segments"]
                airline = segments[0].get("carrierCode", "??")
                stops = len(segments) - 1

                # Resolve airline name from dictionaries
                carriers = data.get("dictionaries", {}).get("carriers", {})
                airline_name = carriers.get(airline, airline)

                fares.append(FareResult(
                    origin=origin,
                    destination=destination,
                    airline=airline_name,
                    price=price,
                    currency="GBP",
                    departure_date=departure_date,
                    return_date=return_date,
                    cabin_class=CabinClass.ECONOMY,
                    stops=stops,
                    source="amadeus",
                    raw_data=offer,
                ))
            except (KeyError, ValueError) as e:
                logger.debug("Skipping malformed offer: %s", e)

        return fares

    async def search_cheapest_dates(self, origin: str,
                                      destination: str) -> list[FareResult]:
        """
        Use the Flight Cheapest Date Search endpoint to find
        the lowest fares across a range of dates.
        """
        await self.authenticate()

        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/v1/shopping/flight-dates",
                headers={"Authorization": f"Bearer {self.access_token}"},
                params={
                    "origin": origin,
                    "destination": destination,
                    "oneWay": "false",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Amadeus cheapest dates failed %s→%s: %s", origin, destination, e)
            return []

        fares = []
        for item in data.get("data", []):
            try:
                fares.append(FareResult(
                    origin=origin,
                    destination=destination,
                    airline="Various",
                    price=float(item["price"]["total"]),
                    currency=data.get("meta", {}).get("currency", "GBP"),
                    departure_date=item["departureDate"],
                    return_date=item.get("returnDate"),
                    cabin_class=CabinClass.ECONOMY,
                    stops=-1,  # Unknown from this endpoint
                    source="amadeus_dates",
                    raw_data=item,
                ))
            except (KeyError, ValueError):
                continue

        return fares

    async def get_price_analysis(self, origin: str, destination: str,
                                  departure_date: str) -> Optional[dict]:
        """
        Use Flight Price Analysis to get historical context.
        Returns percentiles and whether a price is a good deal.
        """
        await self.authenticate()
        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/v1/analytics/itinerary-price-metrics",
                headers={"Authorization": f"Bearer {self.access_token}"},
                params={
                    "originIataCode": origin,
                    "destinationIataCode": destination,
                    "departureDate": departure_date,
                    "currencyCode": "GBP",
                    "oneWay": "false",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("data"):
                metrics = data["data"][0]["priceMetrics"]
                return {m["quartileRanking"]: float(m["amount"]) for m in metrics}
        except Exception as e:
            logger.debug("Price analysis unavailable: %s", e)
        return None

    async def close(self):
        await self.client.aclose()


class KiwiSource:
    """
    Kiwi.com Tequila API adapter.
    Docs: https://tequila.kiwi.com
    Good for budget carriers and virtual interlining.
    """
    BASE_URL = "https://api.tequila.kiwi.com"

    def __init__(self):
        self.api_key = Config.KIWI_API_KEY
        self.client = httpx.AsyncClient(timeout=30)

    async def search_flights(self, origin: str, destination: str = None,
                              date_from: str = None,
                              date_to: str = None) -> list[FareResult]:
        """
        Search flights. If no destination, searches everywhere
        (great for finding anomalies).
        """
        params = {
            "fly_from": origin,
            "date_from": date_from or (datetime.utcnow() + timedelta(days=14)).strftime("%d/%m/%Y"),
            "date_to": date_to or (datetime.utcnow() + timedelta(days=180)).strftime("%d/%m/%Y"),
            "nights_in_dst_from": 3,
            "nights_in_dst_to": 14,
            "flight_type": "round",
            "curr": "GBP",
            "locale": "en",
            "limit": 50,
            "sort": "price",
            "asc": 1,
        }
        if destination:
            params["fly_to"] = destination

        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/v2/search",
                headers={"apikey": self.api_key},
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Kiwi search failed from %s: %s", origin, e)
            return []

        fares = []
        for flight in data.get("data", []):
            try:
                fares.append(FareResult(
                    origin=origin,
                    destination=flight.get("flyTo", "???"),
                    airline=flight.get("airlines", ["Unknown"])[0],
                    price=float(flight["price"]),
                    currency="GBP",
                    departure_date=flight.get("local_departure", "")[:10],
                    return_date=flight.get("local_arrival", "")[:10],
                    cabin_class=CabinClass.ECONOMY,
                    stops=len(flight.get("route", [])) // 2 - 1,
                    source="kiwi",
                    booking_url=flight.get("deep_link"),
                    raw_data=flight,
                ))
            except (KeyError, ValueError):
                continue

        return fares

    async def close(self):
        await self.client.aclose()


# ══════════════════════════════════════════════════════════════
# Anomaly Detection Engine
# ══════════════════════════════════════════════════════════════

class AnomalyDetector:
    """
    Detects pricing anomalies using statistical analysis.

    Classification:
      - Error Fare:  > 65% below average, very rare
      - Flash Sale:  40-65% below average, expires quickly
      - Price Drop:  30-40% below average, sustained reduction
      - Hidden Fare: Available only via specific OTAs/routes
    """

    def __init__(self, db: PriceDatabase):
        self.db = db

    async def analyze_fare(self, fare: FareResult) -> Optional[Deal]:
        """Analyze a single fare against historical data."""

        # Get historical stats for this route
        stats = await self.db.get_route_stats(
            fare.origin, fare.destination,
            days=Config.PRICE_HISTORY_DAYS,
        )

        if not stats:
            logger.debug("No history for %s→%s, storing for baseline",
                         fare.origin, fare.destination)
            return None

        if stats["datapoints"] < Config.MIN_HISTORICAL_DATAPOINTS:
            logger.debug("Insufficient data for %s→%s (%d points)",
                         fare.origin, fare.destination, stats["datapoints"])
            return None

        avg_price = stats["avg_price"]
        min_price = stats["min_price"]
        std_dev = stats["std_dev"]

        # Calculate how anomalous this fare is
        savings_pct = ((avg_price - fare.price) / avg_price) * 100

        if savings_pct < Config.ANOMALY_THRESHOLD_PCT:
            return None  # Not anomalous enough

        # Classify the deal type
        deal_type = self._classify_deal(fare, savings_pct, stats)

        # Calculate confidence score
        confidence = self._calculate_confidence(fare, savings_pct, stats)

        # Skip if already alerted
        if await self.db.is_already_alerted(fare.fare_hash):
            logger.debug("Already alerted for %s", fare.fare_hash)
            return None

        # Estimate expiry
        expires = self._estimate_expiry(deal_type)

        # Generate analysis text
        analysis = self._generate_analysis(fare, deal_type, savings_pct, stats)

        return Deal(
            fare=fare,
            deal_type=deal_type,
            savings_pct=savings_pct,
            avg_price=avg_price,
            min_price=min_price,
            confidence=confidence,
            expires_estimate=expires,
            analysis=analysis,
        )

    def _classify_deal(self, fare: FareResult, savings_pct: float,
                        stats: dict) -> DealType:
        """Classify the type of deal based on pricing patterns."""

        if savings_pct >= Config.ERROR_FARE_THRESHOLD_PCT:
            return DealType.ERROR_FARE

        if savings_pct >= 50:
            # Check if it's from a single source (hidden fare)
            return DealType.FLASH_SALE

        if fare.price < stats["min_price"] * 0.9:
            return DealType.PRICE_DROP

        return DealType.PRICE_DROP

    def _calculate_confidence(self, fare: FareResult, savings_pct: float,
                                stats: dict) -> float:
        """
        Calculate confidence score (0-100) that this is a genuine deal.

        Factors:
        - More historical data = higher confidence
        - More standard deviations below mean = higher confidence
        - Known reliable source = higher confidence
        """
        score = 50.0

        # Data quality bonus (up to +20)
        dp = stats["datapoints"]
        score += min(20, dp * 0.5)

        # Z-score bonus (up to +20)
        if stats["std_dev"] > 0:
            z_score = (stats["avg_price"] - fare.price) / stats["std_dev"]
            score += min(20, z_score * 5)

        # Savings magnitude bonus (up to +10)
        score += min(10, savings_pct * 0.15)

        return min(99, max(10, score))

    def _estimate_expiry(self, deal_type: DealType) -> str:
        estimates = {
            DealType.ERROR_FARE: "1-4 hours (act immediately)",
            DealType.FLASH_SALE: "6-12 hours",
            DealType.PRICE_DROP: "1-3 days",
            DealType.HIDDEN_FARE: "12-48 hours",
        }
        return estimates[deal_type]

    def _generate_analysis(self, fare: FareResult, deal_type: DealType,
                            savings_pct: float, stats: dict) -> str:
        """Generate human-readable analysis of the deal."""

        if deal_type == DealType.ERROR_FARE:
            return (
                f"🚨 PROBABLE ERROR FARE: This {fare.origin}→{fare.destination} "
                f"fare is {savings_pct:.0f}% below the 90-day average of "
                f"£{stats['avg_price']:.0f}. Pattern suggests a currency "
                f"conversion error or missing surcharges. Book immediately "
                f"and avoid contacting the airline."
            )
        elif deal_type == DealType.FLASH_SALE:
            return (
                f"🔥 FLASH SALE: {fare.airline} appears to be running an "
                f"unadvertised sale on this route. Price is {savings_pct:.0f}% "
                f"below normal. Typically these last 6-12 hours."
            )
        elif deal_type == DealType.PRICE_DROP:
            return (
                f"📉 PRICE DROP: Fares on {fare.origin}→{fare.destination} "
                f"have dropped {savings_pct:.0f}% below the average. This "
                f"could be seasonal adjustment or competitive pricing."
            )
        else:
            return (
                f"🔍 HIDDEN FARE: This price is only available via "
                f"{fare.source}. Not visible on airline direct booking. "
                f"Savings of {savings_pct:.0f}% vs typical fares."
            )


# ══════════════════════════════════════════════════════════════
# Alert Dispatcher
# ══════════════════════════════════════════════════════════════

class AlertDispatcher:
    """Multi-channel alert system."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15)

    async def dispatch(self, deal: Deal, channels: list[str] = None):
        """Send deal alert via configured channels."""
        channels = channels or ["telegram", "email"]
        results = {}

        for channel in channels:
            try:
                if channel == "telegram":
                    results["telegram"] = await self._send_telegram(deal)
                elif channel == "email":
                    results["email"] = await self._send_email(deal)
                elif channel == "webhook":
                    results["webhook"] = await self._send_webhook(deal)
            except Exception as e:
                logger.error("Alert dispatch failed [%s]: %s", channel, e)
                results[channel] = False

        return results

    async def _send_telegram(self, deal: Deal) -> bool:
        """Send alert via Telegram bot."""
        if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
            logger.warning("Telegram not configured")
            return False

        text = deal.to_alert_text()
        resp = await self.client.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": Config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        if resp.status_code == 200:
            logger.info("✅ Telegram alert sent: %s→%s £%.0f",
                        deal.fare.origin, deal.fare.destination, deal.fare.price)
            return True
        else:
            logger.error("Telegram failed: %s", resp.text)
            return False

    async def _send_email(self, deal: Deal) -> bool:
        """Send alert via SendGrid."""
        if not Config.SENDGRID_API_KEY or not Config.ALERT_EMAIL:
            logger.warning("Email not configured")
            return False

        subject_prefix = {
            DealType.ERROR_FARE: "🚨 ERROR FARE",
            DealType.FLASH_SALE: "🔥 FLASH SALE",
            DealType.PRICE_DROP: "📉 PRICE DROP",
            DealType.HIDDEN_FARE: "🔍 HIDDEN FARE",
        }[deal.deal_type]

        subject = (
            f"{subject_prefix}: {deal.fare.origin}→{deal.fare.destination} "
            f"£{deal.fare.price:.0f} ({deal.savings_pct:.0f}% off)"
        )

        resp = await self.client.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {Config.SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": Config.ALERT_EMAIL}]}],
                "from": {"email": "alerts@fareradar.app", "name": "FareRadar"},
                "subject": subject,
                "content": [{"type": "text/plain", "value": deal.to_alert_text()}],
            },
        )
        return resp.status_code in (200, 202)

    async def _send_webhook(self, deal: Deal) -> bool:
        """Send to a generic webhook (e.g., Slack, Discord, Pushover)."""
        webhook_url = os.getenv("WEBHOOK_URL")
        if not webhook_url:
            return False

        resp = await self.client.post(webhook_url, json={
            "text": deal.to_alert_text(),
            "deal": {
                "origin": deal.fare.origin,
                "destination": deal.fare.destination,
                "price": deal.fare.price,
                "savings_pct": deal.savings_pct,
                "deal_type": deal.deal_type.value,
                "airline": deal.fare.airline,
            },
        })
        return resp.status_code == 200

    async def close(self):
        await self.client.aclose()


# ══════════════════════════════════════════════════════════════
# Route Generator
# ══════════════════════════════════════════════════════════════

# Top destinations from UK airports (by search volume / deal frequency)
POPULAR_DESTINATIONS = [
    # Europe short-haul
    "BCN", "LIS", "ATH", "FCO", "CDG", "AMS", "BER", "VIE", "PRG",
    "BUD", "DUB", "CPH", "OSL", "ARN", "HEL", "WAW", "ZAG", "SPU",
    "DBV", "IST", "KEF", "RAK", "FNC",
    # Long-haul
    "JFK", "LAX", "SFO", "MIA", "BOS", "ORD", "YYZ", "MEX", "CUN",
    "BOG", "LIM", "EZE", "GRU", "SCL",
    "NRT", "HND", "ICN", "BKK", "SIN", "HKG", "DEL", "BOM", "CMB",
    "DPS", "MLE", "PEK", "PVG", "TPE",
    "CPT", "JNB", "NBO", "DAR", "CMN",
    "SYD", "MEL", "AKL",
]


def generate_scan_routes() -> list[tuple[str, str]]:
    """Generate origin-destination pairs to scan."""
    routes = []
    for origin in Config.DEPARTURE_AIRPORTS:
        for dest in POPULAR_DESTINATIONS:
            if origin != dest:
                routes.append((origin, dest))
    return routes


def generate_search_dates() -> list[str]:
    """Generate departure dates to search across."""
    dates = []
    now = datetime.utcnow()
    for week_offset in range(2, Config.SEARCH_WINDOW_MONTHS * 4 + 1, 2):
        d = now + timedelta(weeks=week_offset)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates


# ══════════════════════════════════════════════════════════════
# Main Scanner Orchestrator
# ══════════════════════════════════════════════════════════════

class FareRadarScanner:
    """
    Main orchestrator that coordinates:
    1. Route generation
    2. Multi-source fare fetching
    3. Anomaly detection
    4. Alert dispatch
    """

    def __init__(self):
        self.db = PriceDatabase()
        self.detector = AnomalyDetector(self.db)
        self.dispatcher = AlertDispatcher()
        self.sources = []

    async def initialize(self):
        """Initialize all components."""
        await self.db.initialize()

        # Initialize available sources
        if Config.AMADEUS_API_KEY:
            self.sources.append(AmadeusSource())
            logger.info("✅ Amadeus source enabled")
        if Config.KIWI_API_KEY:
            self.sources.append(KiwiSource())
            logger.info("✅ Kiwi source enabled")

        if not self.sources:
            logger.error("❌ No fare sources configured! Set API keys.")
            sys.exit(1)

    async def scan_once(self) -> list[Deal]:
        """Execute a single scan pass across all routes."""
        scan_start = datetime.utcnow()
        routes = generate_scan_routes()
        dates = generate_search_dates()

        logger.info("🔍 Starting scan: %d routes × %d dates = %d queries",
                     len(routes), len(dates), len(routes) * len(dates))

        all_fares = []
        all_deals = []
        errors = 0

        # Scan with rate limiting (avoid hammering APIs)
        for i, (origin, dest) in enumerate(routes):
            for source in self.sources:
                try:
                    if isinstance(source, AmadeusSource):
                        # Use cheapest dates endpoint (more efficient)
                        fares = await source.search_cheapest_dates(origin, dest)
                    elif isinstance(source, KiwiSource):
                        fares = await source.search_flights(origin, dest)
                    else:
                        fares = []

                    if fares:
                        all_fares.extend(fares)
                        await self.db.store_fares_batch(fares)

                        # Check each fare for anomalies
                        for fare in fares:
                            deal = await self.detector.analyze_fare(fare)
                            if deal:
                                all_deals.append(deal)
                                await self.db.store_deal(deal)
                                await self.dispatcher.dispatch(deal)
                                logger.info(
                                    "🎯 DEAL FOUND: %s %s→%s £%.0f (-%0.f%%)",
                                    deal.deal_type.value, fare.origin,
                                    fare.destination, fare.price,
                                    deal.savings_pct,
                                )

                except Exception as e:
                    errors += 1
                    logger.error("Scan error %s→%s: %s", origin, dest, e)

                # Rate limiting: ~1 request per second
                await asyncio.sleep(1.0)

            # Progress logging
            if (i + 1) % 50 == 0:
                logger.info("📊 Progress: %d/%d routes scanned, %d fares, %d deals",
                             i + 1, len(routes), len(all_fares), len(all_deals))

        scan_end = datetime.utcnow()
        duration = (scan_end - scan_start).total_seconds()

        await self.db.log_scan(
            scan_start, scan_end, len(routes),
            len(all_fares), len(all_deals), errors,
        )

        logger.info(
            "✅ Scan complete in %.1fs: %d routes, %d fares, %d deals, %d errors",
            duration, len(routes), len(all_fares), len(all_deals), errors,
        )

        return all_deals

    async def run_loop(self):
        """Run the scanner in a continuous loop."""
        logger.info("🚀 FareRadar starting continuous scan loop")
        logger.info("   Interval: %d minutes", Config.SCAN_INTERVAL_MINUTES)
        logger.info("   Airports: %s", ", ".join(Config.DEPARTURE_AIRPORTS))
        logger.info("   Threshold: %.0f%% below average", Config.ANOMALY_THRESHOLD_PCT)

        while True:
            try:
                deals = await self.scan_once()
                if deals:
                    logger.info("🎉 Found %d deals this scan!", len(deals))
            except Exception as e:
                logger.error("Scan loop error: %s", e)

            logger.info("💤 Sleeping %d minutes until next scan...",
                        Config.SCAN_INTERVAL_MINUTES)
            await asyncio.sleep(Config.SCAN_INTERVAL_MINUTES * 60)

    async def shutdown(self):
        """Clean up resources."""
        for source in self.sources:
            await source.close()
        await self.dispatcher.close()
        logger.info("FareRadar shut down")


# ══════════════════════════════════════════════════════════════
# CLI Entry Point
# ══════════════════════════════════════════════════════════════

async def main():
    scanner = FareRadarScanner()
    await scanner.initialize()

    try:
        if "--scan-once" in sys.argv:
            await scanner.scan_once()
        elif "--backfill" in sys.argv:
            logger.info("Running backfill mode...")
            await scanner.scan_once()
        else:
            await scanner.run_loop()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await scanner.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
