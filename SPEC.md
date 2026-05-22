# Wealth Dashboard — SPEC

## Overview
Standalone web app for portfolio management via Alpaca. Self-hosted on iMac, accessed via Tailscale from anywhere.

## Architecture
- Frontend: Vite + React + TypeScript + Recharts
- Data: Alpaca Trading API (read positions/orders) + Hermes cron (analysis pipeline)
- Strategy: Fundamental → Opportunistic → Market Event → Politically Aligned → Quantitative Arbitrage

## Pages

### 1. Portfolio Overview
- Holdings table: ticker, shares, avg cost, current price, market value, gain/loss ($), gain/loss (%)
- Performance line chart: portfolio value over time (daily/weekly/monthly toggle)
- Allocation pie chart: % breakdown by sector/asset class

### 2. Analysis + Recommendations
- Latest Hermes/Claude Code output: stock ratings (BUY/SELL/HOLD/WAIT)
- Each recommendation: ticker, action, target price, rationale, strategy type (1-5)
- Filter by strategy type

### 3. Trade Approvals ← Actionable
- Pending orders from Alpaca
- Each order: ticker, side (buy/sell), qty, price, status, time submitted
- APPROVE / REJECT buttons with confirmation
- On APPROVE: Hermes calls Alpaca API → order executes → confirmation logged
- Order history with execution status

### 4. Market Watch
- Watchlist with live-ish prices (polling every 30s)
- 52-week high/low, volume, % change
- Market sector performance heatmap

## Data Flow
```
Alpaca API ──GET positions/orders──▶ Hermes (cron job)
                                       │
                                       ▼
                              analysis.json + recommendations.json
                                       │
                                       ▼
                              Web Dashboard (fetch JSON)
```

## Tech Stack
- Vite 9 + React 19 + TypeScript
- Recharts (charts)
- Lucide (icons)
- Axios (HTTP)
- Alpaca SDK (@ Trading API v2)

## Deployment
- Dev: `npm run dev` on iMac → accessible via Tailscale:9157
- Future: Docker on Mac Pro or cheap VPS