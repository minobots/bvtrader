#!/usr/local/bin/python3
"""Fetch Alpaca data and write JSON for the wealth dashboard. Uses direct REST API."""
import os, json, requests
from datetime import datetime

API_KEY = os.environ.get("ALPACA_API_KEY")
API_SECRET = os.environ.get("ALPACA_API_SECRET")
PAPER = True
BASE_URL = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
HEADERS = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": API_SECRET}

DATA_DIR = os.path.expanduser("~/.hermes/cron/output/wealth")
os.makedirs(DATA_DIR, exist_ok=True)

if not API_KEY or not API_SECRET:
    print("ERROR: ALPACA_API_KEY and ALPACA_API_SECRET must be set")
    exit(1)

try:
    # Account
    r = requests.get(f"{BASE_URL}/v2/account", headers=HEADERS, timeout=10)
    r.raise_for_status()
    acct = r.json()
    pv = float(acct["portfolio_value"])
    last_eq = float(acct["last_equity"])
    summary = {
        "totalValue": pv,
        "cash": float(acct["cash"]),
        "equity": float(acct["equity"]),
        "dayChange": pv - last_eq,
        "dayChangePct": (pv - last_eq) / last_eq * 100 if last_eq else 0,
    }

    # Positions
    r = requests.get(f"{BASE_URL}/v2/positions", headers=HEADERS, timeout=10)
    r.raise_for_status()
    raw_positions = r.json()
    pos_data = []
    for p in raw_positions:
        pos_data.append({
            "symbol": p["symbol"],
            "name": p["symbol"],
            "qty": float(p["qty"]),
            "avgEntryPrice": float(p["avg_entry_price"]),
            "currentPrice": float(p["current_price"]),
            "marketValue": float(p["market_value"]),
            "unrealizedPL": float(p["unrealized_pl"]),
            "unrealizedPLPct": float(p["unrealized_plpc"]) * 100,
            "sector": "Unknown",
        })

    # Orders
    r = requests.get(f"{BASE_URL}/v2/orders?status=all&limit=50", headers=HEADERS, timeout=10)
    r.raise_for_status()
    raw_orders = r.json()
    order_data = []
    for o in raw_orders:
        order_data.append({
            "id": o["id"],
            "symbol": o["symbol"],
            "side": o["side"],
            "qty": float(o["qty"]),
            "type": o["order_type"],
            "limitPrice": float(o["limit_price"]) if o.get("limit_price") else None,
            "status": o["status"],
            "createdAt": o["created_at"],
            "filledAt": o.get("filled_at"),
        })

    with open(f"{DATA_DIR}/positions.json", "w") as f:
        json.dump(pos_data, f, indent=2)
    with open(f"{DATA_DIR}/orders.json", "w") as f:
        json.dump(order_data, f, indent=2)
    with open(f"{DATA_DIR}/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    import time
    now_utc = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())
    print(f"[{now_utc}] OK: {len(pos_data)} positions, {len(order_data)} orders, portfolio=${pv:.2f}")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    exit(1)