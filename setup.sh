#!/bin/bash
# FareRadar Free — Quick Setup
# Run: chmod +x setup.sh && ./setup.sh

set -e

echo "📡 FareRadar Free — Setup"
echo "═══════════════════════════════════════"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required. Install from python.org"
    exit 1
fi
echo "✅ Python $(python3 --version | cut -d' ' -f2)"

# Install deps
echo ""
echo "Installing dependencies..."
pip install httpx aiosqlite --quiet 2>/dev/null || pip install httpx aiosqlite --quiet --break-system-packages
echo "✅ Core dependencies installed"

# Try installing Google Flights scraper (optional)
echo ""
echo "Installing Google Flights scraper (optional)..."
if pip install fast-flights --quiet 2>/dev/null || pip install fast-flights --quiet --break-system-packages 2>/dev/null; then
    echo "✅ fast-flights installed (Phase 4 enabled)"
else
    echo "⚠️  fast-flights not available — Phase 4 will be skipped"
    echo "   This is fine, phases 1-3 handle the heavy lifting"
fi

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    if [ -f .env.free ]; then
        cp .env.free .env
        echo ""
        echo "📝 Created .env from .env.free template"
    fi
fi

echo ""
echo "═══════════════════════════════════════"
echo "Setup complete! Next steps:"
echo ""
echo "1. Get your free API keys:"
echo "   • SerpAPI:  https://serpapi.com"
echo "   • Amadeus:  https://developers.amadeus.com"
echo "   • Kiwi:     https://tequila.kiwi.com"
echo "   • Telegram: message @BotFather"
echo ""
echo "2. Edit .env with your keys:"
echo "   nano .env"
echo ""
echo "3. Run a single scan:"
echo "   python3 fare_radar_free.py --once"
echo ""
echo "4. Run continuously (every 30 min):"
echo "   python3 fare_radar_free.py"
echo ""
echo "5. Run via cron (add to crontab -e):"
echo "   */30 * * * * cd $(pwd) && python3 fare_radar_free.py --once >> scan.log 2>&1"
echo ""
echo "═══════════════════════════════════════"
