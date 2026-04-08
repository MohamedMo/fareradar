import { useState, useEffect, useCallback } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Area, AreaChart, BarChart, Bar, Cell } from "recharts";

// ── Simulated Data ──────────────────────────────────────────
const AIRPORTS = {
  LHR: "London Heathrow", LGW: "London Gatwick", MAN: "Manchester",
  EDI: "Edinburgh", BHX: "Birmingham", STN: "London Stansted",
  JFK: "New York JFK", LAX: "Los Angeles", ORD: "Chicago O'Hare",
  SFO: "San Francisco", BOS: "Boston", MIA: "Miami",
};

const AIRLINES = ["British Airways", "Ryanair", "EasyJet", "Norwegian", "Wizz Air", "TAP Portugal", "Iberia", "KLM", "Lufthansa", "Turkish Airlines", "Air France", "Emirates", "Qatar Airways", "Singapore Airlines", "Cathay Pacific"];

const DESTINATIONS = [
  { city: "Tokyo", code: "NRT", country: "Japan", region: "Asia", flag: "🇯🇵" },
  { city: "New York", code: "JFK", country: "USA", region: "North America", flag: "🇺🇸" },
  { city: "Bangkok", code: "BKK", country: "Thailand", region: "Asia", flag: "🇹🇭" },
  { city: "Barcelona", code: "BCN", country: "Spain", region: "Europe", flag: "🇪🇸" },
  { city: "Lisbon", code: "LIS", country: "Portugal", region: "Europe", flag: "🇵🇹" },
  { city: "Bali", code: "DPS", country: "Indonesia", region: "Asia", flag: "🇮🇩" },
  { city: "Cape Town", code: "CPT", country: "South Africa", region: "Africa", flag: "🇿🇦" },
  { city: "Buenos Aires", code: "EZE", country: "Argentina", region: "South America", flag: "🇦🇷" },
  { city: "Reykjavik", code: "KEF", country: "Iceland", region: "Europe", flag: "🇮🇸" },
  { city: "Marrakech", code: "RAK", country: "Morocco", region: "Africa", flag: "🇲🇦" },
  { city: "Seoul", code: "ICN", country: "South Korea", region: "Asia", flag: "🇰🇷" },
  { city: "Mexico City", code: "MEX", country: "Mexico", region: "North America", flag: "🇲🇽" },
  { city: "Athens", code: "ATH", country: "Greece", region: "Europe", flag: "🇬🇷" },
  { city: "Colombo", code: "CMB", country: "Sri Lanka", region: "Asia", flag: "🇱🇰" },
  { city: "Nairobi", code: "NBO", country: "Kenya", region: "Africa", flag: "🇰🇪" },
];

const DEAL_TYPES = ["error_fare", "flash_sale", "price_drop", "hidden_fare"];
const DEAL_LABELS = { error_fare: "Error Fare", flash_sale: "Flash Sale", price_drop: "Price Drop", hidden_fare: "Hidden Fare" };
const DEAL_COLORS = { error_fare: "#ff3366", flash_sale: "#ff9500", price_drop: "#00cc88", hidden_fare: "#7c5cfc" };

function generateHistoricalPrices(basePrice) {
  const data = [];
  let price = basePrice;
  for (let i = 30; i >= 0; i--) {
    price = Math.max(basePrice * 0.7, Math.min(basePrice * 1.4, price + (Math.random() - 0.48) * basePrice * 0.08));
    const d = new Date(); d.setDate(d.getDate() - i);
    data.push({ date: d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }), price: Math.round(price), avg: Math.round(basePrice) });
  }
  return data;
}

function generateDeals() {
  const deals = [];
  const now = Date.now();
  for (let i = 0; i < 18; i++) {
    const dest = DESTINATIONS[Math.floor(Math.random() * DESTINATIONS.length)];
    const origins = Object.keys(AIRPORTS);
    const origin = origins[Math.floor(Math.random() * origins.length)];
    const airline = AIRLINES[Math.floor(Math.random() * AIRLINES.length)];
    const type = DEAL_TYPES[Math.floor(Math.random() * DEAL_TYPES.length)];
    const normalPrice = dest.region === "Europe" ? 150 + Math.random() * 200 : 400 + Math.random() * 600;
    const discount = type === "error_fare" ? 0.15 + Math.random() * 0.2 : 0.4 + Math.random() * 0.3;
    const dealPrice = Math.round(normalPrice * discount);
    const savings = Math.round((1 - discount) * 100);
    const minutesAgo = Math.floor(Math.random() * 360);
    const travelMonth = ["May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov"][Math.floor(Math.random() * 7)];
    deals.push({
      id: `deal-${i}`,
      destination: dest,
      origin,
      airline,
      type,
      price: dealPrice,
      normalPrice: Math.round(normalPrice),
      savings,
      foundAt: new Date(now - minutesAgo * 60000),
      minutesAgo,
      travelDates: `${travelMonth} 2026`,
      returnTrip: Math.random() > 0.3,
      cabinClass: Math.random() > 0.85 ? "Business" : "Economy",
      historicalPrices: generateHistoricalPrices(Math.round(normalPrice)),
      confidence: Math.round(70 + Math.random() * 30),
      expiresIn: type === "error_fare" ? `~${1 + Math.floor(Math.random() * 4)}h` : `~${4 + Math.floor(Math.random() * 20)}h`,
      stops: Math.random() > 0.6 ? 0 : Math.random() > 0.5 ? 1 : 2,
    });
  }
  return deals.sort((a, b) => a.minutesAgo - b.minutesAgo);
}

function generateScanStats() {
  return {
    routesMonitored: 2847193,
    faresScanned: 14283947,
    dealsFound: 47,
    errorFares: 3,
    avgSavings: 68,
    lastScan: "12s ago",
    scanRate: 4218,
  };
}

// ── Components ──────────────────────────────────────────────

function PulseIndicator({ color = "#00cc88", size = 8 }) {
  return (
    <span style={{ position: "relative", display: "inline-block", width: size, height: size, marginRight: 8 }}>
      <span style={{
        position: "absolute", inset: -2, borderRadius: "50%", background: color, opacity: 0.3,
        animation: "pulse 2s ease-in-out infinite"
      }} />
      <span style={{ display: "block", width: size, height: size, borderRadius: "50%", background: color }} />
    </span>
  );
}

function StatCard({ label, value, sub, accent = false }) {
  return (
    <div style={{
      background: "var(--card)", border: "1px solid var(--border)",
      borderRadius: 14, padding: "20px 22px", flex: "1 1 160px", minWidth: 160,
      ...(accent ? { borderColor: "var(--accent)", boxShadow: "0 0 20px rgba(255,51,102,0.1)" } : {})
    }}>
      <div style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1.5, marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: accent ? "var(--accent)" : "var(--text)", fontFamily: "var(--display)", lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6, fontFamily: "var(--mono)" }}>{sub}</div>}
    </div>
  );
}

function DealTypeBadge({ type }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "3px 10px", borderRadius: 6, fontSize: 11, fontWeight: 600,
      fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: 0.8,
      background: DEAL_COLORS[type] + "18", color: DEAL_COLORS[type],
      border: `1px solid ${DEAL_COLORS[type]}30`,
    }}>
      {type === "error_fare" && "⚡"}{type === "flash_sale" && "🔥"}{type === "price_drop" && "📉"}{type === "hidden_fare" && "🔍"}
      {" "}{DEAL_LABELS[type]}
    </span>
  );
}

function DealCard({ deal, isSelected, onClick }) {
  const timeLabel = deal.minutesAgo < 60
    ? `${deal.minutesAgo}m ago`
    : `${Math.floor(deal.minutesAgo / 60)}h ${deal.minutesAgo % 60}m ago`;

  return (
    <div onClick={onClick} style={{
      background: isSelected ? "var(--card-active)" : "var(--card)",
      border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
      borderRadius: 14, padding: "18px 20px", cursor: "pointer",
      transition: "all 0.2s ease",
      ...(isSelected ? { boxShadow: "0 0 24px rgba(255,51,102,0.08)" } : {}),
      ...(deal.type === "error_fare" ? { borderLeft: `3px solid ${DEAL_COLORS.error_fare}` } : {}),
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 28 }}>{deal.destination.flag}</span>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text)", fontFamily: "var(--display)" }}>
              {deal.destination.city}
            </div>
            <div style={{ fontSize: 12, color: "var(--muted)", fontFamily: "var(--mono)" }}>
              {deal.origin} → {deal.destination.code} · {deal.airline}
            </div>
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 24, fontWeight: 800, color: "var(--accent)", fontFamily: "var(--display)" }}>
            £{deal.price}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", textDecoration: "line-through", fontFamily: "var(--mono)" }}>
            £{deal.normalPrice}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <DealTypeBadge type={deal.type} />
          <span style={{ fontSize: 11, color: "var(--green)", fontWeight: 600, fontFamily: "var(--mono)" }}>
            ↓{deal.savings}% off
          </span>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)" }}>
            {deal.returnTrip ? "Return" : "One-way"} · {deal.cabinClass} · {deal.stops === 0 ? "Direct" : `${deal.stops} stop${deal.stops > 1 ? "s" : ""}`}
          </span>
          <span style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)" }}>
            {timeLabel}
          </span>
        </div>
      </div>
    </div>
  );
}

function DealDetail({ deal, onReview }) {
  if (!deal) return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center", height: "100%",
      color: "var(--muted)", fontFamily: "var(--mono)", fontSize: 13, padding: 40,
      textAlign: "center", flexDirection: "column", gap: 12
    }}>
      <span style={{ fontSize: 40, opacity: 0.3 }}>📡</span>
      <span>Select a deal to view price history and booking details</span>
    </div>
  );

  return (
    <div style={{ padding: "24px 28px", overflowY: "auto", height: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
            <span style={{ fontSize: 36 }}>{deal.destination.flag}</span>
            <div>
              <h2 style={{ fontSize: 24, fontWeight: 800, color: "var(--text)", margin: 0, fontFamily: "var(--display)" }}>
                {deal.destination.city}, {deal.destination.country}
              </h2>
              <div style={{ fontSize: 13, color: "var(--muted)", fontFamily: "var(--mono)", marginTop: 2 }}>
                {AIRPORTS[deal.origin]} → {deal.destination.code}
              </div>
            </div>
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 36, fontWeight: 800, color: "var(--accent)", fontFamily: "var(--display)" }}>£{deal.price}</div>
          <DealTypeBadge type={deal.type} />
        </div>
      </div>

      {/* Info Grid */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12, marginBottom: 24
      }}>
        {[
          { l: "Airline", v: deal.airline },
          { l: "Cabin", v: deal.cabinClass },
          { l: "Route Type", v: deal.returnTrip ? "Return" : "One-way" },
          { l: "Stops", v: deal.stops === 0 ? "Direct" : `${deal.stops} stop${deal.stops > 1 ? "s" : ""}` },
          { l: "Travel Window", v: deal.travelDates },
          { l: "Est. Expiry", v: deal.expiresIn },
          { l: "Normal Price", v: `£${deal.normalPrice}` },
          { l: "Confidence", v: `${deal.confidence}%` },
        ].map((item, i) => (
          <div key={i} style={{
            background: "var(--bg)", borderRadius: 10, padding: "12px 14px",
            border: "1px solid var(--border)"
          }}>
            <div style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: 1.2, marginBottom: 4 }}>{item.l}</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", fontFamily: "var(--body)" }}>{item.v}</div>
          </div>
        ))}
      </div>

      {/* Price History Chart */}
      <div style={{
        background: "var(--bg)", borderRadius: 14, padding: "20px",
        border: "1px solid var(--border)", marginBottom: 20
      }}>
        <div style={{ fontSize: 12, fontFamily: "var(--mono)", color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1.2, marginBottom: 16 }}>
          30-Day Price History
        </div>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={deal.historicalPrices}>
            <defs>
              <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ff3366" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#ff3366" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#666", fontFamily: "monospace" }} axisLine={false} tickLine={false} interval={4} />
            <YAxis tick={{ fontSize: 10, fill: "#666", fontFamily: "monospace" }} axisLine={false} tickLine={false} tickFormatter={v => `£${v}`} domain={["dataMin - 30", "dataMax + 30"]} />
            <Tooltip
              contentStyle={{ background: "#1a1a2e", border: "1px solid #2a2a4a", borderRadius: 8, fontSize: 12, fontFamily: "monospace" }}
              labelStyle={{ color: "#888" }}
              formatter={(v) => [`£${v}`, ""]}
            />
            <Area type="monotone" dataKey="price" stroke="#ff3366" fill="url(#priceGrad)" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="avg" stroke="#555" strokeWidth={1} strokeDasharray="4 4" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
        <div style={{ display: "flex", gap: 20, marginTop: 8 }}>
          <span style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)", display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 16, height: 2, background: "#ff3366", display: "inline-block" }} /> Actual price
          </span>
          <span style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)", display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 16, height: 2, background: "#555", display: "inline-block", borderTop: "1px dashed #555" }} /> Average
          </span>
        </div>
      </div>

      {/* Anomaly Indicator */}
      <div style={{
        background: `${DEAL_COLORS[deal.type]}08`, borderRadius: 14, padding: "16px 20px",
        border: `1px solid ${DEAL_COLORS[deal.type]}20`, marginBottom: 20
      }}>
        <div style={{ fontSize: 12, fontFamily: "var(--mono)", color: DEAL_COLORS[deal.type], fontWeight: 600, marginBottom: 8 }}>
          ⚠ ANOMALY DETECTED
        </div>
        <div style={{ fontSize: 13, color: "var(--text-secondary)", fontFamily: "var(--body)", lineHeight: 1.6 }}>
          This fare is <strong style={{ color: "var(--accent)" }}>{deal.savings}% below</strong> the 90-day rolling average for this route.
          {deal.type === "error_fare" && " Pattern matches known error fare signatures — likely a currency conversion or fuel surcharge omission."}
          {deal.type === "flash_sale" && " This appears to be an unadvertised airline sale. Expect availability for 6-12 hours."}
          {deal.type === "price_drop" && " Consistent price reduction detected across multiple OTAs. Likely a genuine fare adjustment."}
          {deal.type === "hidden_fare" && " This fare is only visible via specific booking paths or OTAs. Not shown on airline direct."}
        </div>
      </div>

      {/* Review status banner */}
      {deal.approved === 1 && (
        <div style={{
          padding: "10px 14px", borderRadius: 10, background: "#0f2a1a",
          border: "1px solid #1f5a33", color: "#80e0a0", fontFamily: "var(--mono)",
          fontSize: 12, marginBottom: 12
        }}>
          ✓ APPROVED — visible to subscribers
        </div>
      )}
      {deal.approved === 0 && (
        <div style={{
          padding: "10px 14px", borderRadius: 10, background: "#2a1a1a",
          border: "1px solid #5a2a2a", color: "#ff9090", fontFamily: "var(--mono)",
          fontSize: 12, marginBottom: 12
        }}>
          ✕ REJECTED
        </div>
      )}

      {/* Action Buttons */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <a
          href={deal.googleFlightsUrl || "#"}
          target="_blank" rel="noreferrer"
          style={{
            flex: 1, padding: "14px 20px", borderRadius: 10, border: "none",
            background: "var(--accent)", color: "white", fontSize: 14, fontWeight: 700,
            fontFamily: "var(--display)", cursor: "pointer", letterSpacing: 0.3,
            minWidth: 160, textAlign: "center", textDecoration: "none",
            opacity: deal.googleFlightsUrl ? 1 : 0.4,
            pointerEvents: deal.googleFlightsUrl ? "auto" : "none",
          }}
        >
          Book via Google Flights ↗
        </a>
        <a
          href={deal.skyscannerUrl || "#"}
          target="_blank" rel="noreferrer"
          style={{
            flex: 1, padding: "14px 20px", borderRadius: 10, border: "1px solid var(--border)",
            background: "var(--card)", color: "var(--text)", fontSize: 14, fontWeight: 600,
            fontFamily: "var(--display)", cursor: "pointer", minWidth: 140,
            textAlign: "center", textDecoration: "none",
            opacity: deal.skyscannerUrl ? 1 : 0.4,
            pointerEvents: deal.skyscannerUrl ? "auto" : "none",
          }}
        >
          Check on Skyscanner ↗
        </a>
      </div>

      {/* Review queue controls */}
      <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
        <button
          onClick={() => onReview?.(deal, "approve")}
          disabled={deal.approved === 1}
          style={{
            flex: 1, padding: "12px 18px", borderRadius: 10,
            border: "1px solid #1f5a33", background: deal.approved === 1 ? "#1f5a33" : "#0f2a1a",
            color: "#80e0a0", fontSize: 13, fontWeight: 700, fontFamily: "var(--display)",
            cursor: deal.approved === 1 ? "default" : "pointer",
          }}
        >
          {deal.approved === 1 ? "✓ Approved" : "Approve ✓"}
        </button>
        <button
          onClick={() => onReview?.(deal, "reject")}
          disabled={deal.approved === 0}
          style={{
            flex: 1, padding: "12px 18px", borderRadius: 10,
            border: "1px solid #5a2a2a", background: deal.approved === 0 ? "#5a2a2a" : "#2a1a1a",
            color: "#ff9090", fontSize: 13, fontWeight: 700, fontFamily: "var(--display)",
            cursor: deal.approved === 0 ? "default" : "pointer",
          }}
        >
          {deal.approved === 0 ? "✕ Rejected" : "Reject ✕"}
        </button>
      </div>
    </div>
  );
}

function ScannerVisualization({ stats }) {
  const [dots, setDots] = useState([]);

  useEffect(() => {
    const interval = setInterval(() => {
      setDots(prev => {
        const next = [...prev, { id: Date.now(), x: Math.random() * 100, y: Math.random() * 100 }];
        return next.slice(-20);
      });
    }, 300);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{
      position: "relative", height: 120, background: "var(--bg)",
      borderRadius: 14, border: "1px solid var(--border)", overflow: "hidden", marginBottom: 20
    }}>
      {/* Scan lines */}
      <div style={{
        position: "absolute", inset: 0, opacity: 0.05,
        backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 3px, var(--text) 3px, var(--text) 4px)",
      }} />

      {/* Dots */}
      {dots.map(dot => (
        <div key={dot.id} style={{
          position: "absolute", left: `${dot.x}%`, top: `${dot.y}%`,
          width: 4, height: 4, borderRadius: "50%",
          background: Math.random() > 0.9 ? "var(--accent)" : "var(--green)",
          opacity: 0.6, animation: "fadeIn 0.5s ease-out",
          boxShadow: Math.random() > 0.9 ? "0 0 8px var(--accent)" : "none"
        }} />
      ))}

      {/* Overlay info */}
      <div style={{
        position: "absolute", inset: 0, display: "flex", alignItems: "center",
        justifyContent: "space-between", padding: "0 24px",
        background: "linear-gradient(90deg, var(--bg) 0%, transparent 30%, transparent 70%, var(--bg) 100%)"
      }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <PulseIndicator color="#00cc88" />
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--green)", fontFamily: "var(--mono)" }}>SCANNER ACTIVE</span>
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)" }}>
            {stats.scanRate.toLocaleString()} fares/sec · Last scan {stats.lastScan}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--text)", fontFamily: "var(--display)" }}>
            {(stats.faresScanned / 1000000).toFixed(1)}M
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)" }}>fares scanned today</div>
        </div>
      </div>
    </div>
  );
}

function FilterBar({ activeFilter, onFilter, activeRegion, onRegion }) {
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 4, background: "var(--bg)", borderRadius: 10, padding: 3, border: "1px solid var(--border)" }}>
        {[
          { key: "all", label: "All Deals" },
          { key: "error_fare", label: "⚡ Error" },
          { key: "flash_sale", label: "🔥 Flash" },
          { key: "price_drop", label: "📉 Drop" },
          { key: "hidden_fare", label: "🔍 Hidden" },
        ].map(f => (
          <button key={f.key} onClick={() => onFilter(f.key)} style={{
            padding: "6px 14px", borderRadius: 8, border: "none", fontSize: 12, fontWeight: 600,
            fontFamily: "var(--mono)", cursor: "pointer", transition: "all 0.15s",
            background: activeFilter === f.key ? "var(--card)" : "transparent",
            color: activeFilter === f.key ? "var(--text)" : "var(--muted)",
            boxShadow: activeFilter === f.key ? "0 1px 4px rgba(0,0,0,0.15)" : "none",
          }}>
            {f.label}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 4, background: "var(--bg)", borderRadius: 10, padding: 3, border: "1px solid var(--border)" }}>
        {["All", "Europe", "Asia", "Africa", "North America", "South America"].map(r => (
          <button key={r} onClick={() => onRegion(r)} style={{
            padding: "6px 12px", borderRadius: 8, border: "none", fontSize: 12, fontWeight: 600,
            fontFamily: "var(--mono)", cursor: "pointer", transition: "all 0.15s",
            background: activeRegion === r ? "var(--card)" : "transparent",
            color: activeRegion === r ? "var(--text)" : "var(--muted)",
          }}>
            {r}
          </button>
        ))}
      </div>
    </div>
  );
}

function SettingsPanel({ onClose }) {
  const [origins, setOrigins] = useState(["LHR", "LGW", "STN"]);
  const [threshold, setThreshold] = useState(40);
  const [notifications, setNotifications] = useState({ email: true, push: true, telegram: false, sms: false });

  const toggleOrigin = (code) => {
    setOrigins(prev => prev.includes(code) ? prev.filter(c => c !== code) : [...prev, code]);
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
      backdropFilter: "blur(8px)"
    }}>
      <div style={{
        background: "var(--card)", borderRadius: 20, padding: "32px",
        maxWidth: 560, width: "100%", maxHeight: "80vh", overflowY: "auto",
        border: "1px solid var(--border)", boxShadow: "0 24px 48px rgba(0,0,0,0.3)"
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
          <h2 style={{ fontSize: 22, fontWeight: 800, color: "var(--text)", margin: 0, fontFamily: "var(--display)" }}>Scanner Settings</h2>
          <button onClick={onClose} style={{
            background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 8,
            width: 32, height: 32, display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", color: "var(--text)", fontSize: 16
          }}>×</button>
        </div>

        {/* Departure Airports */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontSize: 12, fontFamily: "var(--mono)", color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1.2, marginBottom: 12 }}>
            Departure Airports
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {Object.entries(AIRPORTS).map(([code, name]) => (
              <button key={code} onClick={() => toggleOrigin(code)} style={{
                padding: "8px 14px", borderRadius: 8, fontSize: 12, fontFamily: "var(--mono)",
                border: `1px solid ${origins.includes(code) ? "var(--accent)" : "var(--border)"}`,
                background: origins.includes(code) ? "var(--accent)15" : "var(--bg)",
                color: origins.includes(code) ? "var(--accent)" : "var(--muted)",
                cursor: "pointer", fontWeight: 600
              }}>
                {code}
              </button>
            ))}
          </div>
        </div>

        {/* Anomaly Threshold */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontSize: 12, fontFamily: "var(--mono)", color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1.2, marginBottom: 12 }}>
            Anomaly Threshold (min % below average)
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <input type="range" min="20" max="80" value={threshold} onChange={e => setThreshold(e.target.value)}
              style={{ flex: 1, accentColor: "var(--accent)" }} />
            <span style={{ fontSize: 20, fontWeight: 800, color: "var(--accent)", fontFamily: "var(--display)", minWidth: 50, textAlign: "right" }}>{threshold}%</span>
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)", marginTop: 6 }}>
            Lower = more deals but more noise. Higher = fewer but stronger deals.
          </div>
        </div>

        {/* Notification Channels */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontSize: 12, fontFamily: "var(--mono)", color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1.2, marginBottom: 12 }}>
            Alert Channels
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {[
              { key: "email", label: "Email Alerts", emoji: "📧", desc: "Digest every 30 min or instant for error fares" },
              { key: "push", label: "Push Notifications", emoji: "🔔", desc: "Instant via mobile app" },
              { key: "telegram", label: "Telegram Bot", emoji: "💬", desc: "Instant messages to your Telegram" },
              { key: "sms", label: "SMS (Error Fares Only)", emoji: "📱", desc: "Text alerts for confirmed error fares" },
            ].map(ch => (
              <div key={ch.key} onClick={() => setNotifications(prev => ({ ...prev, [ch.key]: !prev[ch.key] }))} style={{
                display: "flex", alignItems: "center", gap: 14, padding: "12px 16px",
                borderRadius: 10, border: `1px solid ${notifications[ch.key] ? "var(--accent)" : "var(--border)"}`,
                background: notifications[ch.key] ? "var(--accent)08" : "var(--bg)",
                cursor: "pointer", transition: "all 0.15s"
              }}>
                <span style={{ fontSize: 22 }}>{ch.emoji}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", fontFamily: "var(--body)" }}>{ch.label}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)" }}>{ch.desc}</div>
                </div>
                <div style={{
                  width: 40, height: 22, borderRadius: 11, padding: 2,
                  background: notifications[ch.key] ? "var(--accent)" : "var(--border)",
                  transition: "all 0.2s", display: "flex", alignItems: "center",
                  justifyContent: notifications[ch.key] ? "flex-end" : "flex-start"
                }}>
                  <div style={{ width: 18, height: 18, borderRadius: "50%", background: "white", transition: "all 0.2s" }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <button onClick={onClose} style={{
          width: "100%", padding: "14px", borderRadius: 10, border: "none",
          background: "var(--accent)", color: "white", fontSize: 15, fontWeight: 700,
          fontFamily: "var(--display)", cursor: "pointer"
        }}>
          Save Settings
        </button>
      </div>
    </div>
  );
}

// ── Main App ────────────────────────────────────────────────

// ── Enrich an API deal with dashboard-side destination metadata ──
const UNKNOWN_DEST = { city: "Unknown", code: "???", country: "", region: "Other", flag: "🌍" };

function enrichDeal(apiDeal) {
  const dest =
    DESTINATIONS.find(d => d.code === apiDeal.destinationCode) ||
    { ...UNKNOWN_DEST, code: apiDeal.destinationCode || "???", city: apiDeal.destName || "Unknown" };

  const mins = apiDeal.minutesAgo ?? 0;
  const expiresIn =
    apiDeal.type === "error_fare"
      ? `~${1 + Math.floor(Math.random() * 4)}h`
      : `~${4 + Math.floor(Math.random() * 20)}h`;

  return {
    id: apiDeal.id,                       // numeric DB id, used by approve/reject endpoints
    destination: dest,
    origin: apiDeal.origin || "LHR",
    airline: apiDeal.airline,
    type: apiDeal.type,
    price: apiDeal.price,
    normalPrice: apiDeal.normalPrice,
    savings: apiDeal.savings,
    foundAt: new Date(apiDeal.sentAt),
    minutesAgo: mins,
    travelDates: apiDeal.departureDate
      ? new Date(apiDeal.departureDate).toLocaleDateString("en-GB", { month: "short", year: "numeric" })
      : "Flexible",
    returnTrip: true,
    cabinClass: apiDeal.cabinClass || "Economy",
    historicalPrices: [], // lazily loaded when a deal is selected
    confidence: apiDeal.confidence,
    expiresIn,
    stops: 0,
    approved: apiDeal.approved,
    googleFlightsUrl: apiDeal.googleFlightsUrl,
    skyscannerUrl: apiDeal.skyscannerUrl,
  };
}

export default function FareRadar() {
  const [deals, setDeals] = useState([]);
  const [stats, setStats] = useState({
    routesMonitored: 0, faresScanned: 0, dealsFound: 0,
    errorFares: 0, avgSavings: 0, lastScan: "—", scanRate: 0,
  });
  const [selectedDeal, setSelectedDeal] = useState(null);
  const [filter, setFilter] = useState("all");
  const [region, setRegion] = useState("All");
  const [showSettings, setShowSettings] = useState(false);
  const [view, setView] = useState("feed"); // feed | detail (mobile)
  const [apiError, setApiError] = useState(null);

  const filteredDeals = deals.filter(d => {
    if (filter !== "all" && d.type !== filter) return false;
    if (region !== "All" && d.destination.region !== region) return false;
    return true;
  });

  const reviewDeal = async (deal, action) => {
    const newApproved = action === "approve" ? 1 : 0;
    try {
      const r = await fetch(`/api/deals/${deal.id}/${action}`, { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      // Optimistic local update — no need to wait for the next poll.
      setDeals(ds => ds.map(d => d.id === deal.id ? { ...d, approved: newApproved } : d));
      setSelectedDeal(d => d && d.id === deal.id ? { ...d, approved: newApproved } : d);
    } catch (e) {
      setApiError(`Review failed: ${e.message}`);
    }
  };

  const selectDeal = async (deal) => {
    setSelectedDeal(deal);
    setView("detail");
    // Lazy-load the price history for this route from the real API.
    if (deal.origin && deal.destination.code && deal.historicalPrices.length === 0) {
      try {
        const r = await fetch(`/api/history?origin=${deal.origin}&destination=${deal.destination.code}`);
        if (r.ok) {
          const data = await r.json();
          if (data.points?.length) {
            setSelectedDeal({ ...deal, historicalPrices: data.points });
          }
        }
      } catch (e) { /* keep empty chart */ }
    }
  };

  // Fetch real deals + stats, poll every 10s.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [dealsRes, statsRes] = await Promise.all([
          fetch("/api/deals"),
          fetch("/api/stats"),
        ]);
        if (!dealsRes.ok || !statsRes.ok) throw new Error(`HTTP ${dealsRes.status}/${statsRes.status}`);
        const dealsData = await dealsRes.json();
        const statsData = await statsRes.json();
        if (cancelled) return;
        setDeals(dealsData.deals.map(enrichDeal));
        setStats(statsData);
        setApiError(null);
      } catch (e) {
        if (!cancelled) setApiError(e.message || "API unreachable");
      }
    }
    load();
    const interval = setInterval(load, 10000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  return (
    <div style={{
      "--bg": "#0d0d1a",
      "--card": "#151528",
      "--card-active": "#1a1a35",
      "--border": "#222240",
      "--text": "#e8e8f0",
      "--text-secondary": "#a0a0b8",
      "--muted": "#666680",
      "--accent": "#ff3366",
      "--green": "#00cc88",
      "--mono": "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace",
      "--display": "'Outfit', 'Sora', sans-serif",
      "--body": "'DM Sans', 'Nunito Sans', sans-serif",
      background: "var(--bg)", color: "var(--text)", minHeight: "100vh",
      fontFamily: "var(--body)"
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
        @keyframes pulse { 0%, 100% { transform: scale(1); opacity: 0.3; } 50% { transform: scale(2.2); opacity: 0; } }
        @keyframes fadeIn { from { opacity: 0; transform: scale(0); } to { opacity: 0.6; transform: scale(1); } }
        * { box-sizing: border-box; scrollbar-width: thin; scrollbar-color: #333 transparent; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
      `}</style>

      {/* Header */}
      <header style={{
        padding: "16px 24px", borderBottom: "1px solid var(--border)",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        position: "sticky", top: 0, zIndex: 100, background: "var(--bg)",
        backdropFilter: "blur(12px)"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {view === "detail" && (
            <button onClick={() => setView("feed")} style={{
              background: "none", border: "none", color: "var(--text)", cursor: "pointer",
              fontSize: 18, padding: "4px 8px", display: "none",
            }}>
              ←
            </button>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 10, background: "linear-gradient(135deg, #ff3366, #ff6b35)",
              display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18
            }}>📡</div>
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, fontFamily: "var(--display)", letterSpacing: -0.5 }}>
                FareRadar
              </div>
              <div style={{ fontSize: 10, fontFamily: "var(--mono)", color: "var(--muted)", letterSpacing: 1 }}>
                AUTONOMOUS FARE INTELLIGENCE
              </div>
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <PulseIndicator color="#00cc88" size={6} />
            <span style={{ fontSize: 12, fontFamily: "var(--mono)", color: "var(--green)" }}>LIVE</span>
          </div>
          <button onClick={() => setShowSettings(true)} style={{
            padding: "8px 16px", borderRadius: 8, border: "1px solid var(--border)",
            background: "var(--card)", color: "var(--text)", fontSize: 12,
            fontFamily: "var(--mono)", cursor: "pointer", fontWeight: 600
          }}>
            ⚙ Settings
          </button>
        </div>
      </header>

      {apiError && (
        <div style={{
          padding: "10px 24px", background: "#3a1a1a", borderBottom: "1px solid #5a2a2a",
          color: "#ff9090", fontFamily: "var(--mono)", fontSize: 12,
        }}>
          ⚠ API unreachable ({apiError}) — start it with: <code style={{color:"#fff"}}>uvicorn src.api:app --port 8000</code>
        </div>
      )}

      {/* Stats Row */}
      <div style={{ padding: "20px 24px 0" }}>
        <ScannerVisualization stats={stats} />
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 }}>
          <StatCard
            label="Routes Monitored"
            value={stats.routesMonitored >= 1000
              ? `${(stats.routesMonitored / 1000).toFixed(1)}K`
              : stats.routesMonitored.toLocaleString()}
            sub={`${stats.faresScanned.toLocaleString()} fares in DB`}
          />
          <StatCard label="Deals Found Today" value={stats.dealsFound} sub={`${stats.errorFares} error fares`} accent />
          <StatCard label="Avg Savings" value={`${stats.avgSavings}%`} sub="below market rate" />
          <StatCard label="Last Scan" value={stats.lastScan} sub="from scanner" />
        </div>
      </div>

      {/* Main Content */}
      <div style={{ padding: "0 24px 24px" }}>
        <FilterBar activeFilter={filter} onFilter={setFilter} activeRegion={region} onRegion={setRegion} />

        <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
          {/* Deal Feed */}
          <div style={{ flex: "1 1 420px", minWidth: 0 }}>
            <div style={{
              fontSize: 12, fontFamily: "var(--mono)", color: "var(--muted)",
              marginBottom: 12, textTransform: "uppercase", letterSpacing: 1.2
            }}>
              {filteredDeals.length} Active Deals
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {filteredDeals.map(deal => (
                <DealCard
                  key={deal.id}
                  deal={deal}
                  isSelected={selectedDeal?.id === deal.id}
                  onClick={() => selectDeal(deal)}
                />
              ))}
            </div>
          </div>

          {/* Detail Panel */}
          <div style={{
            flex: "1 1 480px", minWidth: 0, position: "sticky", top: 80,
            background: "var(--card)", borderRadius: 16, border: "1px solid var(--border)",
            minHeight: 400, maxHeight: "calc(100vh - 100px)", overflowY: "auto",
          }}>
            <DealDetail deal={selectedDeal} onReview={reviewDeal} />
          </div>
        </div>
      </div>

      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </div>
  );
}
