#!/usr/bin/python3
"""
Wealth Dashboard backend — Alpaca API bridge.
Fetches positions/orders from Alpaca, serves them over HTTP to the React frontend.
Run: python3 wealth_backend.py
"""
import os, json, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

API_KEY = os.environ.get("ALPACA_API_KEY", "PKYBN34XEJMJA46ZVPNIALRKIP")
API_SECRET = os.environ.get("ALPACA_API_SECRET", "Bw6TbtEaZN6zSeLBGd2NZiWHijiSi7GHD4fgtzb5hvoA")
PAPER = True

DATA_DIR = os.path.expanduser("~/.hermes/cron/output/wealth")
os.makedirs(DATA_DIR, exist_ok=True)

client = TradingClient(API_KEY, API_SECRET, paper=PAPER)


def java_time():
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def fetch_and_save():
    """Fetch positions + orders from Alpaca and write JSON files."""
    # Positions
    positions = client.get_all_positions()
    pos_data = []
    for p in positions:
        pos_data.append({
            "symbol": p.symbol,
            "name": p.symbol,
            "qty": float(p.qty),
            "avgEntryPrice": float(p.avg_entry_price),
            "currentPrice": float(p.current_price),
            "marketValue": float(p.market_value),
            "unrealizedPL": float(p.unrealized_pl),
            "unrealizedPLPct": float(p.unrealized_plpc) * 100,
            "sector": "Unknown",
        })

    # Orders
    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, limit=50))
    order_data = []
    for o in orders:
        order_data.append({
            "id": o.id,
            "symbol": o.symbol,
            "side": str(o.side).lower(),
            "qty": float(o.qty),
            "type": str(o.order_type).lower(),
            "limitPrice": float(o.limit_price) if o.limit_price else None,
            "status": str(o.status).lower(),
            "createdAt": o.created_at.isoformat() + "Z",
            "filledAt": o.filled_at.isoformat() + "Z" if o.filled_at else None,
        })

    # Portfolio summary
    account = client.get_account()
    pv = float(account.portfolio_value)
    last_eq = float(account.last_equity)
    summary = {
        "totalValue": pv,
        "cash": float(account.cash),
        "equity": float(account.equity),
        "dayChange": pv - last_eq,
        "dayChangePct": (pv - last_eq) / last_eq * 100 if last_eq else 0,
    }

    with open(f"{DATA_DIR}/positions.json", "w") as f:
        json.dump(pos_data, f, indent=2)
    with open(f"{DATA_DIR}/orders.json", "w") as f:
        json.dump(order_data, f, indent=2)
    with open(f"{DATA_DIR}/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[{java_time()}] Saved: {len(pos_data)} positions, {len(order_data)} orders, portfolio={pv:.2f}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[HTTP] {fmt % args}")

    def do_GET(self):
        if self.path == "/positions":
            path = f"{DATA_DIR}/positions.json"
        elif self.path == "/orders":
            path = f"{DATA_DIR}/orders.json"
        elif self.path == "/summary":
            path = f"{DATA_DIR}/summary.json"
        else:
            self.send_error(404, "not found")
            return

        try:
            with open(path) as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data.encode())
        except FileNotFoundError:
            self.send_error(404, "no data yet — run fetch first")

    def do_POST(self):
        if self.path == "/fetch":
            fetch_and_save()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return

        if self.path.startswith("/order/"):
            parts = self.path.split("/")
            if len(parts) == 4 and parts[3] in ("approve", "reject"):
                order_id = parts[2]
                action = parts[3]
                try:
                    if action == "approve":
                        order = client.get_order_by_id(order_id)
                        result = {"status": "approved", "order_id": order_id, "symbol": order.symbol}
                    else:
                        client.cancel_order_by_id(order_id)
                        result = {"status": "cancelled", "order_id": order_id}
                    response = json.dumps(result)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(response.encode())
                except Exception as e:
                    self.send_error(400, str(e))
                return

        self.send_error(404, "not found")


if __name__ == "__main__":
    port = 8765

    print("Fetching Alpaca data...")
    fetch_and_save()

    server = HTTPServer(("localhost", port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"Backend running on http://localhost:{port}")
    print(f"  GET  /positions  /orders  /summary")
    print(f"  POST /fetch  /order/<id>/approve  /order/<id>/reject")

    t.join()