#!/usr/bin/python3
"""
Wealth Dashboard backend — Alpaca API bridge + scoring engine.
Fetches positions/orders from Alpaca, serves them over HTTP to the React frontend.
Run: python3 wealth_backend.py
"""
import os, json, threading, time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest
from alpaca.trading.enums import QueryOrderStatus, OrderSide, TimeInForce

API_KEY = os.environ.get("ALPACA_API_KEY", "PKYBN34XEJMJA46ZVPNIALRKIP")
API_SECRET = os.environ.get("ALPACA_API_SECRET", "Bw6TbtEaZN6zSeLBGd2NZiWHijiSi7GHD4fgtzb5hvoA")
PAPER = True

DATA_DIR = os.path.expanduser("~/.hermes/cron/output/wealth")
SCAN_FILE = os.path.join(DATA_DIR, "market_scan.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
os.makedirs(DATA_DIR, exist_ok=True)

client = TradingClient(API_KEY, API_SECRET, paper=PAPER)

# ── Sector mapping (symbol → sector) ─────────────────────────────────────────
SECTOR_MAP = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "GOOGL": "Technology", "GOOG": "Technology", "META": "Technology",
    "AMZN": "Consumer Cyclical", "TSLA": "Consumer Cyclical",
    "JPM": "Financial", "BAC": "Financial", "V": "Financial",
    "JNJ": "Healthcare", "UNH": "Healthcare", "LLY": "Healthcare",
    "XOM": "Energy", "CVX": "Energy",
    "SPY": "Index ETF", "QQQ": "Index ETF", "SOXX": "Sector ETF",
    "XLE": "Sector ETF", "XLK": "Sector ETF", "XLV": "Sector ETF",
    "KO": "Consumer Defensive", "PG": "Consumer Defensive",
    "INTC": "Technology", "AMD": "Technology",
}

# ── Company names (symbol → full name) ───────────────────────────────────────
COMPANY_NAMES = {
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corp.", "NVDA": "NVIDIA Corp.",
    "GOOGL": "Alphabet Inc.", "GOOG": "Alphabet Inc.", "META": "Meta Platforms",
    "AMZN": "Amazon.com Inc.", "TSLA": "Tesla Inc.",
    "JPM": "JPMorgan Chase", "BAC": "Bank of America", "V": "Visa Inc.",
    "JNJ": "Johnson & Johnson", "UNH": "UnitedHealth Group", "LLY": "Eli Lilly",
    "XOM": "Exxon Mobil", "CVX": "Chevron Corp.",
    "SPY": "S&P 500 ETF", "QQQ": "Nasdaq 100 ETF", "SOXX": "Semiconductor ETF",
    "XLE": "Energy Sector ETF", "XLK": "Tech Sector ETF", "XLV": "Healthcare Sector ETF",
    "KO": "Coca-Cola Co.", "PG": "Procter & Gamble",
    "INTC": "Intel Corp.", "AMD": "Advanced Micro Devices",
}

def _get_sector(symbol):
    return SECTOR_MAP.get(symbol, "Other")

def _get_name(symbol):
    return COMPANY_NAMES.get(symbol, symbol)

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


def _now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


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
            "name": _get_name(p.symbol),
            "qty": float(p.qty),
            "avgEntryPrice": float(p.avg_entry_price),
            "currentPrice": float(p.current_price),
            "marketValue": float(p.market_value),
            "unrealizedPL": float(p.unrealized_pl),
            "unrealizedPLPct": float(p.unrealized_plpc) * 100,
            "sector": _get_sector(p.symbol),
        })

    # Orders
    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, limit=50))
    order_data = []
    for o in orders:
        order_data.append({
            "id": str(o.id),
            "symbol": o.symbol,
            "side": str(o.side).lower(),
            "qty": float(o.qty) if o.qty else 0,
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

    print(f"[{_now_str()}] Saved: {len(pos_data)} positions, {len(order_data)} orders, portfolio=${pv:.2f}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[HTTP] {fmt % args}")

    def _send_json(self, data, status=200):
        body = json.dumps(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

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
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT s.symbol, s.name, s.asset_type, s.sector, s.industry, s.market_cap, s.exchange,
                           sc.f_rule1总分 as rule1_score,
                           sc.composite_score, sc.scan_status, sc.q_rule5总分 as rule5_score,
                           sc.o_rule2总分 as rule2_score, sc.m_rule3总分 as rule3_score,
                           sc.p_rule4总分 as rule4_score, sc.t_rule6总分 as rule6_score,
                           sc.current_price, sc.fifty_two_high,
                           f.pe_ratio, f.forward_pe, f.peg_ratio,
                           f.eps_growth_5y as eps_growth, f.rev_growth_1y as rev_growth,
                           f.roe, f.profit_margin, f.debt_to_equity,
                           f.div_yield
                    FROM stocks s
                    LEFT JOIN scores sc ON sc.symbol = s.symbol AND sc.score_date = date('now')
                    LEFT JOIN fundamentals f ON f.symbol = s.symbol
                    ORDER BY
                        CASE WHEN s.asset_type = 'crypto' THEN 0 WHEN s.asset_type = 'etf' THEN 1 ELSE 2 END,
                        COALESCE(sc.composite_score, sc.f_rule1总分, 0) DESC
                    LIMIT 500
                """).fetchall()
            except Exception as e:
                print(f"[library] DB error: {e}")
                self._send_json({"count": 0, "symbols": [], "error": str(e)})
                return
            finally:
                conn.close()
            symbols = []
            crypto_count = 0
            stock_count = 0
            for r in rows:
                def fmt_f(v):
                    if v is None or (isinstance(v, float) and math.isnan(v)):
                        return None
                    return round(float(v), 2) if v is not None else None
                asset_type = r["asset_type"] or "stock"
                sym_data = {
                    "symbol":       r["symbol"],
                    "name":         r["name"] or r["symbol"],
                    "assetType":    asset_type,
                    "sector":       r["sector"] or "",
                    "industry":     r["industry"] or "",
                    "marketCap":    r["market_cap"],
                    "exchange":     r["exchange"],
                    "rule1Score":   fmt_f(r["rule1_score"]),
                    "compositeScore": fmt_f(r["composite_score"]),
                    "scanStatus":   r["scan_status"] or "",
                    "rule5Score":   fmt_f(r["rule5_score"]),
                    "rule2Score":   fmt_f(r["rule2_score"]),
                    "rule3Score":   fmt_f(r["rule3_score"]),
                    "rule4Score":   fmt_f(r["rule4_score"]),
                    "rule6Score":   fmt_f(r["rule6_score"]),
                    "currentPrice": fmt_f(r["current_price"]),
                    "fiftyTwoHigh": fmt_f(r["fifty_two_high"]),
                    "peRatio":      fmt_f(r["pe_ratio"]),
                    "forwardPe":    fmt_f(r["forward_pe"]),
                    "pegRatio":     fmt_f(r["peg_ratio"]),
                    "epsGrowth":    fmt_f(r["eps_growth"]),
                    "revGrowth":    fmt_f(r["rev_growth"]),
                    "roe":          fmt_f(r["roe"]),
                    "profitMargin": fmt_f(r["profit_margin"]),
                    "debtToEquity": fmt_f(r["debt_to_equity"]),
                    "divYield":     fmt_f(r["div_yield"]),
                }
                symbols.append(sym_data)
                if asset_type == "crypto":
                    crypto_count += 1
                else:
                    stock_count += 1
            self._send_json({"count": len(symbols), "symbols": symbols, "cryptoCount": crypto_count, "stockCount": stock_count})
            return
        elif self.path == "/day_trades":
            from pathlib import Path
            import sqlite3
            DB_PATH = str(Path.home() / ".hermes/cron/output/wealth/portfolio.db")
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                # Recent signals
                signals = conn.execute("""
                    SELECT symbol, signal_date, signal_time, strategy, signal,
                           confidence, entry_price, stop_loss, take_profit, status, notes
                    FROM day_trades
                    ORDER BY id DESC LIMIT 50
                """).fetchall()
                # Active trades
                active = conn.execute("""
                    SELECT symbol, side, entry_price, qty, notional, stop_loss,
                           take_profit, strategy, confidence, entry_time, status,
                           exit_price, exit_time, pnl, pnl_pct
                    FROM active_day_trades
                    WHERE status = 'open'
                    ORDER BY entry_time DESC
                """).fetchall()
                # Closed trades today
                closed = conn.execute("""
                    SELECT symbol, side, entry_price, exit_price, pnl_pct,
                           exit_time, strategy
                    FROM active_day_trades
                    WHERE status IN ('closed', 'stopped', 'taken_profit')
                    AND exit_time LIKE ?
                    ORDER BY exit_time DESC
                """, (f"{time.strftime('%Y-%m-%d')}%",)).fetchall()
                conn.close()

                self._send_json({
                    "signals": [dict(s) for s in signals],
                    "activeTrades": [dict(t) for t in active],
                    "closedToday": [dict(c) for c in closed],
                    "activeCount": len(active),
                    "signalCount": len(signals),
                })
            except Exception as e:
                self._send_json({"error": str(e), "signals": [], "activeTrades": [], "closedToday": []})
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
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b''

        if self.path == "/fetch":
            fetch_and_save()
            self._send_json({"status": "ok"})
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
            except subprocess.TimeoutExpired:
                result = {"status": "error", "message": "Scan timed out after 5 minutes"}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self._send_json(result)
            return

        if self.path == "/day_trades/scan":
            import subprocess, sys
            try:
                proc = subprocess.run(
                    [sys.executable, "day_trading_engine.py"],
                    capture_output=True, text=True, timeout=120,
                    cwd="/Volumes/Minobot iMac/Projects/wealth-dashboard"
                )
                self._send_json({
                    "status": "ok",
                    "output": proc.stdout[-1000:] if proc.stdout else "",
                    "returncode": proc.returncode,
                })
            except subprocess.TimeoutExpired:
                self._send_json({"status": "error", "message": "Day trading scan timed out"})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)})
            return

        if self.path.startswith("/order/"):
            parts = self.path.split("/")
            if len(parts) == 4 and parts[3] in ("approve", "reject"):
                order_id = parts[2]
                action = parts[3]
                try:
                    if action == "approve":
                        # Actually submit the order to Alpaca
                        # First get the pending order details to re-submit
                        order = client.get_order_by_id(order_id)
                        # Submit a new market order
                        qty = float(order.qty) if order.qty else 0
                        side = OrderSide.BUY if str(order.side).lower() == "buy" else OrderSide.SELL
                        market_order = MarketOrderRequest(
                            symbol=order.symbol,
                            qty=qty,
                            side=side,
                            time_in_force=TimeInForce.DAY
                        )
                        submitted = client.submit_order(market_order)
                        result = {"status": "approved", "order_id": str(submitted.id), "symbol": order.symbol, "submitted_id": str(submitted.id)}
                    else:
                        client.cancel_order_by_id(order_id)
                        result = {"status": "cancelled", "order_id": order_id}
                    self._send_json(result)
                except Exception as e:
                    self._send_json({"status": "error", "message": str(e)}, status=400)
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
    print(f"  GET  /positions  /orders  /summary  /recommendations  /market_scan  /library  /day_trades")
    print(f"  POST /fetch  /scan  /order/<id>/approve  /order/<id>/reject  /day_trades/scan")

    t.join()
