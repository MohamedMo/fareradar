# 📡 FareRadar

An open-source flight deal scanner that finds error fares, flash sales, and price drops — built to compete with services like Jack's Flight Club and Going, using only free-tier APIs.

**Total monthly cost: £0.**

## How it works

Airlines publish fares through ATPCO → GDS platforms (Amadeus, Sabre) process them → consumer search engines (Google Flights, Skyscanner) display them. When someone at an airline makes a pricing mistake — wrong currency conversion, missing fuel surcharge, typo — the error propagates through this chain. FareRadar catches it.

```
Phase 1A: Amadeus Inspiration ──→ "explore everywhere" (cached, 1 call = all destinations)
Phase 1B: SerpAPI Google Explore ─→ independent second source
Phase 1C: Reddit + RSS ──────────→ community-spotted deals (free, no API)
     │
     ▼
Phase 2:  Anomaly Detection ─────→ seasonality-aware (Amadeus Price Analysis ML)
     │
     ▼
Phase 3:  Cross-source verify ───→ confirm fare exists across multiple sources
     │
     ▼
Phase 4:  Alert dispatch ────────→ Telegram (auto-send or human review queue)
```

### What makes it different from a naive price tracker

- **Seasonality-aware**: Uses Amadeus's ML-trained Price Analysis API, not just rolling averages. Knows that £400 to Bangkok in August is a deal even though January fares are £300.
- **Works from day one**: No cold-start problem — Amadeus has years of historical data already.
- **Community monitoring**: Scrapes Reddit and SecretFlying RSS for deals humans spot before any API updates.
- **Human review queue**: Telegram inline keyboard lets you approve/reject deals before subscribers see them.
- **Data validation**: Rejects garbage prices, validates currencies, checks sanity bounds.
- **Budget enforcement**: Tracks every API call and auto-stops when daily limits are reached.

## Quick start

### With the dashboard (recommended)

```bash
git clone https://github.com/MohamedMo/fareradar.git
cd fareradar

make setup       # creates .venv, installs Python deps, runs npm install
make seed        # populates the DB with realistic demo data
make dev         # starts API + dashboard in the background
```

Open **http://localhost:5173**. You'll see 12 seeded deals with 30-day
price histories, deep-links to Google Flights and Skyscanner, and an
approve/reject review queue that writes to the SQLite DB.

To run real scans against the seeded DB:

```bash
cp .env.example .env
# Edit .env with your Amadeus + SerpAPI keys (both free — see below)
make scanner     # one-shot scan; the dashboard polls every 10s
```

`make stop` kills the background API + dashboard processes.
`make test` runs a smoke test that exercises every endpoint.

### Scanner only (headless)

```bash
make setup
cp .env.example .env    # fill in keys
.venv/bin/python src/scanner.py          # run loop (every 20 min)
.venv/bin/python src/scanner.py --once   # single pass
```

### Full stack in Docker

```bash
cp .env.example .env    # fill in keys
docker compose up -d --build
```

- Dashboard → http://localhost:8080 (nginx → api service)
- API → http://localhost:8000

## Architecture

```
┌─────────────┐    ┌────────────┐    ┌──────────────┐
│  scanner.py │───▶│ SQLite DB  │◀───│   api.py     │
│  (20-min    │    │ prices /   │    │  (FastAPI)   │
│   loop)     │    │ alerts /   │    │              │
└─────────────┘    │ scan_runs  │    └──────┬───────┘
                   └────────────┘           │
                                            ▼
                                    ┌──────────────┐
                                    │  React SPA   │
                                    │  (Vite)      │
                                    └──────────────┘
```

- `src/scanner.py` — the scan loop (4 phases, see diagram above)
- `src/api.py` — FastAPI backend exposing `/api/deals`, `/api/stats`,
  `/api/history`, `/api/health`, and POST `/api/deals/:id/{approve,reject}`
- `src/seed_demo.py` — idempotent demo-data seeder
- `dashboard/` — React + Vite SPA that polls the API every 10s

## Free API keys

| Service | Free tier | Sign up | What it gives you |
|---------|-----------|---------|-------------------|
| **Amadeus** | 2,000 calls/month | [developers.amadeus.com](https://developers.amadeus.com) | Flight Inspiration, Price Analysis, Cheapest Dates |
| **SerpAPI** | 250 queries/month | [serpapi.com](https://serpapi.com) | Google Travel Explore (everywhere search) |
| **Telegram** | Unlimited | Message [@BotFather](https://t.me/BotFather) | Instant push alerts |
| Reddit | No auth needed | — | Community deal monitoring |
| RSS | No auth needed | — | SecretFlying feed |

Total setup time: ~15 minutes.

## Project structure

```
fareradar/
├── src/
│   ├── scanner.py          # Scan loop — 4 phases, writes to SQLite
│   ├── scanner_lite.py     # Alternate: simpler 4-phase pipeline
│   ├── scanner_full.py     # Alternate: extended Kiwi integration
│   ├── api.py              # FastAPI backend for the dashboard
│   └── seed_demo.py        # Demo-data seeder (idempotent)
├── dashboard/              # React + Vite SPA
│   ├── App.jsx             #   main component, fetches /api/*
│   ├── main.jsx
│   ├── index.html
│   ├── vite.config.js      #   proxies /api → localhost:8000
│   ├── Dockerfile          #   multi-stage build → nginx
│   └── nginx.conf          #   production /api proxy → api service
├── .env.example            # Configuration template
├── requirements.txt
├── Dockerfile              # Single image for scanner + api
├── docker-compose.yml      # Full stack: scanner + api + dashboard
├── Makefile                # make setup / seed / dev / test / docker-up
└── README.md
```

## Versions

**`scanner.py` (v2, recommended)** — Seasonality-aware anomaly detection using Amadeus Price Analysis, dual explore-everywhere sources (Amadeus Inspiration + SerpAPI), community monitoring (Reddit + RSS), human review queue via Telegram, data validation, and health tracking.

**`scanner_lite.py`** — Simpler 4-phase pipeline: SerpAPI explore → Amadeus verify → Kiwi deep scan → Google Flights scrape. Good starting point for understanding the architecture.

**`scanner_full.py`** — Extended version with full Kiwi Tequila integration, more alert channels (email via SendGrid, webhooks), and a broader route generator.

## How airline pricing actually works

Understanding the data pipeline is essential to understanding what we're building:

1. **Airlines** set fares across dozens of booking classes per route
2. **ATPCO** (Airline Tariff Publishing Company) validates and distributes ~12 million fare changes daily to the industry
3. **GDS platforms** (Amadeus, Sabre, Travelport) combine ATPCO fares + airline availability + schedules into bookable offers
4. **Consumer APIs** (Google Flights via ITA Matrix, Skyscanner, Kiwi) query GDS data and display it to end users

Error fares happen when airlines file incorrect data into ATPCO — wrong currency, missing surcharges, typos. The error propagates through the entire chain within minutes. Our scanner monitors the consumer API layer, which is 15-30 minutes behind raw ATPCO — the same latency Jack's Flight Club had when it started in 2016.

## How JFC started (and why this approach works)

Jack's Flight Club was founded in September 2016 by one person with £30 and a laptop. Jack Sheldon used free tools — ITA Matrix, Google Flights, Skyscanner — to manually search for deals. He had no ATPCO access, no GDS subscription, no enterprise APIs. The "computer program" that automates searching came later.

JFC grew to 2.3 million members and was acquired by Travelzoo for $12 million in 2020. The sophisticated infrastructure followed the revenue, not the other way around.

FareRadar automates from day one what JFC did manually for its first year. Same data sources (Google Flights and Amadeus both pull from ATPCO), same detection logic (is this price anomalously low?), but without the human sitting at a laptop refreshing ITA Matrix.

## Deployment

### Cron (simplest)

```bash
# Add to crontab -e
*/20 * * * * cd /path/to/fareradar && python src/scanner.py --once >> scan.log 2>&1
```

### Docker

```bash
docker compose up -d
```

### Oracle Cloud free tier (always-free ARM instance)

1. Create an Oracle Cloud account (no credit card for free tier)
2. Launch an ARM Ampere A1 instance (4 OCPU, 24GB RAM — forever free)
3. SSH in, clone the repo, set up cron
4. Runs indefinitely at zero cost

## Known limitations

- **No email delivery** — Telegram only. Adding email (via Resend/SendGrid) is the main gap for subscriber-facing use.
- **Telegram review callbacks aren't handled** — approve/reject from the dashboard is fully wired, but the equivalent Telegram inline-keyboard webhook still isn't.
- **Community phase route parsing is weak** — RSS posts use city names ("Miami – Denver"), and the current regex only matches IATA codes. Fares get captured but routed as `???→???` and filtered by anomaly detection. A city → IATA lookup would close this.
- **No LCC-specific coverage** — Ryanair, EasyJet etc. aren't well represented in Amadeus. Kiwi covers them but its free tier is unreliable.
- **Single-currency** — Assumes GBP. Multi-currency support needs conversion logic.

## Contributing

PRs welcome. The most impactful contributions would be:

1. **Telegram webhook handler** for the review queue approve/reject buttons
2. **FastAPI backend** connecting the scanner DB to the React dashboard
3. **Email delivery** integration (Resend or SendGrid)
4. **Additional fare sources** — Duffel API, Skyscanner affiliate API, direct airline scrapers
5. **Smarter scan scheduling** — prioritise routes that historically produce deals

## License

MIT
