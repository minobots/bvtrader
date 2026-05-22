#!/usr/bin/python3
"""
Wealth Dashboard backend — Alpaca API bridge + scoring engine.
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
SCAN_FILE = os.path.join(DATA_DIR, "market_scan.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
os.makedirs(DATA_DIR, exist_ok=True)

client = TradingClient(API_KEY, API_SECRET, paper=PAPER)

# ── Persistent config (starting capital, etc.) ───────────────────────────────
def _load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def _save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def _get_starting_capital(pv):
    """Return stored starting capital, initializing it on first run."""
    cfg = _load_config()
    if "starting_capital" not in cfg:
        cfg["starting_capital"] = pv
        _save_config(cfg)
        print(f"[CONFIG] Starting capital set to ${pv:,.2f}")
    return cfg["starting_capital"]

# ── Scoring Engine ────────────────────────────────────────────────────────────
try:
    import scoring_engine
    SCORER = scoring_engine.ScoreEngine()
except Exception as e:
    print(f"[WARN] scoring_engine not available: {e}")
    SCORER = None


def java_time():
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _load_scan():
    try:
        with open(SCAN_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _build_recommendations(scan_data):
    """Derive recommendation cards from market scan JSON + scoring engine."""
    if SCORER is None:
        return []
    if not scan_data or scan_data.get("status") == "closed":
        return []
    quotes = scan_data.get("quotes", [])
    if not quotes:
        return []

    scored = []
    for q in quotes:
        symbol = q.get("symbol")
        if not symbol:
            continue
        try:
            score, scores = SCORER.score(symbol)
            scored.append({**q, "score": score, "scores": scores})
        except Exception:
            scored.append({**q, "score": 0, "scores": {}})

    scored.sort(key=lambda x: x["score"], reverse=True)

    recommendations = []
    for item in scored[:8]:
        sym = item["symbol"]
        score = item["score"]
        if score >= 1.5:
            action, strat_name, strat_type = "BUY", "Fundamental", 1
        elif score >= 0.5:
            action, strat_name, strat_type = "HOLD", "Opportunistic", 2
        else:
            continue

        try:
            info = SCORER.get_info(sym)
            price = info.get("current_price") or item.get("currentPrice", 0)
            target = round(price * 1.12, 2) if action == "BUY" else None
        except Exception:
            price = item.get("currentPrice", 0)
            target = round(price * 1.12, 2) if action == "BUY" else None

        top_signals = item.get("scores", {})
        rationale_parts = [f"Rule 1 score: {score:.1f}/5"]
        for key, val in list(top_signals.items())[:2]:
            rationale_parts.append(f"{key}: {val:.0f}/100")
        rationale = ". ".join(rationale_parts)

        recommendations.append({
            "id": f"rec_{sym.lower()}",
            "symbol": sym,
            "action": action,
            "targetPrice": target,
            "currentPrice": price,
            "rationale": rationale,
            "strategyType": strat_type,
            "strategyName": strat_name,
            "timestamp": scan_data.get("timestamp", ""),
            "horizon": "7-14 days" if action == "BUY" else "14-21 days",
            "confidence": min(92, max(50, int(60 + score * 8))),
        })

    return recommendations


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
            "id": str(o.id),
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
    starting_capital = _get_starting_capital(pv)
    summary = {
        "totalValue": pv,
        "cash": float(account.cash),
        "equity": float(account.equity),
        "lastEquity": last_eq,
        "startingCapital": starting_capital,
        "dayChange": pv - last_eq,
        "dayChangePct": (pv - last_eq) / last_eq * 100 if last_eq else 0,
        "totalGain": pv - starting_capital,
        "totalGainPct": (pv - starting_capital) / starting_capital * 100 if starting_capital else 0,
    }

    with open(f"{DATA_DIR}/positions.json", "w") as f:
        json.dump(pos_data, f, indent=2)
    with open(f"{DATA_DIR}/orders.json", "w") as f:
        json.dump(order_data, f, indent=2)
    with open(f"{DATA_DIR}/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[{java_time()}] Saved: {len(pos_data)} positions, {len(order_data)} orders, portfolio=${pv:.2f}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[HTTP] {fmt % args}")

    def _send_json(self, data, status=200):
        body = json.dumps(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if self.path == "/positions":
            path = f"{DATA_DIR}/positions.json"
        elif self.path == "/orders":
            path = f"{DATA_DIR}/orders.json"
        elif self.path == "/summary":
            path = f"{DATA_DIR}/summary.json"
        elif self.path == "/recommendations":
            scan_data = _load_scan()
            recs = _build_recommendations(scan_data) if scan_data else []
            self._send_json(recs)
            return
        elif self.path == "/market_scan":
            scan_data = _load_scan()
            self._send_json(scan_data if scan_data else {"status": "no_data"})
            return
        elif self.path == "/library":
            from pathlib import Path
            DB_PATH = str(Path.home() / ".hermes/cron/output/wealth/portfolio.db")
            import sqlite3, math
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT s.symbol, s.name, s.asset_type, s.exchange,
                       sc.f_rule1总分 as rule1_score,
                       f.pe_ratio, f.forward_pe, f.peg_ratio,
                       f.eps_growth_5y as eps_growth, f.rev_growth_1y as rev_growth,
                       f.roe, f.profit_margin, f.debt_to_equity,
                       f.div_yield
                FROM stocks s
                LEFT JOIN scores sc ON sc.symbol = s.symbol AND sc.score_date = date('now')
                LEFT JOIN fundamentals f ON f.symbol = s.symbol
                WHERE sc.f_rule1总分 IS NOT NULL
                ORDER BY sc.f_rule1总分 DESC
                LIMIT 200
            """).fetchall()
            conn.close()
            symbols = []
            for r in rows:
                def fmt_f(v):
                    if v is None or (isinstance(v, float) and math.isnan(v)):
                        return None
                    return round(float(v), 2) if v is not None else None
                symbols.append({
                    "symbol":       r["symbol"],
                    "name":         r["name"] or r["symbol"],
                    "assetType":    r["asset_type"],
                    "exchange":     r["exchange"],
                    "rule1Score":   fmt_f(r["rule1_score"]),
                    "peRatio":      fmt_f(r["pe_ratio"]),
                    "forwardPe":    fmt_f(r["forward_pe"]),
                    "pegRatio":     fmt_f(r["peg_ratio"]),
                    "epsGrowth":    fmt_f(r["eps_growth"]),
                    "revGrowth":    fmt_f(r["rev_growth"]),
                    "roe":          fmt_f(r["roe"]),
                    "profitMargin": fmt_f(r["profit_margin"]),
                    "debtToEquity": fmt_f(r["debt_to_equity"]),
                    "divYield":     fmt_f(r["div_yield"]),
                })
            self._send_json({"count": len(symbols), "symbols": symbols})
            return
        else:
            self.send_error(404, "not found")
            return

        try:
            with open(path) as f:
                data = json.load(f)
            self._send_json(data)
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

        if self.path == "/scan":
            import subprocess, sys
            result = {}
            try:
                proc = subprocess.run(
                    [sys.executable, "market_scan.py"],
                    capture_output=True, text=True, timeout=300,
                    cwd="/Volumes/Minobot iMac/Projects/wealth-dashboard"
                )
                scan_data = _load_scan()
                result = {"status": "ok", "scan": scan_data, "stdout": proc.stdout[-500:] if proc.stdout else ""}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self._send_json(result)
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
                    self._send_json(result)
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
    print(f"  GET  /positions  /orders  /summary  /recommendations")
    print(f"  POST /fetch  /order/<id>/approve  /order/<id>/reject")

    t.join()