#!/usr/local/bin/python3
"""
Automated Trading Agent — Alex Yu
Hourly execution during trading hours (9:30 AM–4 PM ET, Mon–Fri)
Uses scoring engine to generate signals, executes via Alpaca paper API.
"""
import os, sys, json, time, requests, sqlite3
from datetime import datetime, timedelta

# ── Alpaca Config ────────────────────────────────────────────────────────────
API_KEY = os.environ.get("ALPACA_API_KEY", "PKYBN34XEJMJA46ZVPNIALRKIP")
API_SECRET = os.environ.get("ALPACA_API_SECRET", "Bw6TbtEaZN6zSeLBGd2NZiWHijiSi7GHD4fgtzb5hvoA")
ALPACA_BASE = "https://paper-api.alpaca.markets"
HEADERS = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": API_SECRET}

# ── Watchlist ────────────────────────────────────────────────────────────────
WATCHLIST = ["AAPL", "GOOGL", "QQQ", "V", "XLE", "SOXX", "KO", "CVX", "LLY",
             "INTC", "SPY", "NVDA", "AMZN", "META", "MSFT"]

# ── DB path for signals ──────────────────────────────────────────────────────
DB_PATH = os.path.expanduser("~/.hermes/cron/output/wealth/portfolio.db")

def get_db_signals(min_score=60, limit=20):
    """Fetch active BUY signals from portfolio DB scored by portfolio_manager."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, score_before, score_after, price_at_signal, target_price
            FROM signals
            WHERE status='active'
              AND signal_type='buy'
              AND (score_before >= ? OR score_after >= ?)
            ORDER BY COALESCE(score_after, score_before) DESC
            LIMIT ?
        """, (min_score, min_score, limit))
        rows = cur.fetchall()
        conn.close()
        return [{"symbol": r[0], "db_score": r[1] or r[2], "entry_price": r[3], "target": r[4]} for r in rows]
    except Exception as e:
        return []

# ── Calendar / Fed Engine (same as market_scan.py) ───────────────────────────
FOMC_WINDOWS = [
    (1,28,31),(3,17,20),(5,5,8),(6,16,19),
    (7,28,31),(9,16,19),(10,6,9),(12,15,18),
]
EARNINGS_SEASONS = [(1,8,21),(4,8,21),(7,8,21),(10,8,21)]
ECON_RELEASE_WINDOWS = [(m,5,12) for m in range(1,13)]

def get_calendar_context():
    now = datetime.now()
    month, day, weekday = now.month, now.day, now.weekday()
    pressure = 0.0
    active = []
    in_earnings = any(m==month and s<=day<=e for m,s,e in EARNINGS_SEASONS)
    in_fomc = any(m==month and (e-2)<=day<=(e+1) for m,_,e in FOMC_WINDOWS)
    in_macro = any(m==month and s<=day<=e for m,s,e in ECON_RELEASE_WINDOWS)
    in_cpi = 8<=day<=14
    is_employment_friday = weekday==4 and 1<=day<=14
    in_pension = day>=25 and weekday<5
    is_quarter_end = month in [3,6,9,12] and day>=25
    is_year_end = month==12 and day>=20

    if in_earnings: active.append("Earnings Season"); pressure+=0.25
    if in_fomc: active.append("FOMC Week"); pressure+=0.30
    if in_macro: active.append("Macro Week"); pressure+=0.15
    if in_pension: active.append("Pension Rebalance"); pressure+=0.10
    if is_year_end: active.append("Year-End"); pressure+=0.15
    if is_quarter_end: active.append("Quarter-End"); pressure+=0.05

    return {
        "in_earnings_season": in_earnings,
        "in_fomc_week": in_fomc,
        "in_macro_week": in_macro,
        "in_cpi_week": in_cpi,
        "is_employment_friday": is_employment_friday,
        "in_pension_rebalance": in_pension,
        "is_quarter_end": is_quarter_end,
        "is_year_end": is_year_end,
        "calendar_pressure": min(1.0, pressure),
        "active_windows": active,
        "month": month, "day": day,
    }

CAL_CTX = get_calendar_context()

# ── Fed Regime ───────────────────────────────────────────────────────────────
def get_fed_regime():
    import yfinance as yf
    rd = {"ten_year": None, "two_year": None, "spread_10y2y": None,
          "regime": "unknown", "rate_direction": "neutral",
          "fomc_countdown": None, "minutes_until_fomc": None,
          "fed_watch": "🟡 neutral", "last_updated": None}
    try:
        fi_10 = yf.Ticker("^TNX").fast_info
        fi_2  = yf.Ticker("^FVX").fast_info
        ten = getattr(fi_10,"last_price",None)
        two = getattr(fi_2, "last_price",None)
        if ten: rd["ten_year"] = round(float(ten),3)
        if two: rd["two_year"] = round(float(two),3)
        if ten and two:
            rd["spread_10y2y"] = round(float(ten)-float(two),3)
            if ten > 5.0:   rd["regime"] = "VERY_TIGHT 🔴"; rd["fed_watch"]="🔴 VERY TIGHT"
            elif ten > 4.5: rd["regime"] = "RESTRICTIVE 🟠"; rd["fed_watch"]="🟠 RESTRICTIVE"
            elif ten > 3.5: rd["regime"] = "NEUTRAL 🟡";    rd["fed_watch"]="🟡 NEUTRAL"
            else:           rd["regime"] = "ACCOMMODATIVE 🟢"; rd["fed_watch"]="🟢 ACCOMMODATIVE"
            try:
                t = yf.Ticker("^TNX")
                hist = t.history(period="1mo", interval="1d")
                if hist is not None and len(hist)>=5:
                    ma30 = hist["Close"].mean()
                    if ten > ma30*1.01:   rd["rate_direction"] = "RISING 📈"
                    elif ten < ma30*0.99: rd["rate_direction"] = "FALLING 📉"
                    else:                 rd["rate_direction"] = "STABLE ➡️"
            except: pass
        rd["last_updated"] = datetime.now().strftime("%H:%M ET")
        # FOMC countdown
        now = datetime.now(); year = now.year; next_fomc = None
        for m,d_start,d_end in FOMC_WINDOWS:
            if m >= month:
                fd = datetime(year,m,d_start)
                if fd >= now:
                    next_fomc = fd; break
        if next_fomc:
            delta = next_fomc - now
            rd["fomc_countdown"] = delta.days
            rd["minutes_until_fomc"] = delta.days*24*60
            rd["next_fomc_date"] = next_fomc.strftime("%b %d")
        else:
            rd["fomc_countdown"] = 0; rd["minutes_until_fomc"] = 0; rd["next_fomc_date"]="unknown"
    except Exception as e:
        rd["fed_watch"] = f"⚠️ rate data unavailable: {e}"
    return rd

FED_REGIME = get_fed_regime()

# ── Alpaca Helpers ────────────────────────────────────────────────────────────
def is_market_open():
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/clock", headers=HEADERS, timeout=10)
        if r.status_code==200: return r.json().get("is_open",False)
    except: pass
    now = datetime.utcnow()
    et_hour = (now.hour - 4) % 24
    et_weekday = now.weekday()
    return 9<=et_hour<16 and et_weekday<5

def get_account():
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/account", headers=HEADERS, timeout=10)
        if r.status_code==200:
            a=r.json()
            return {
                "cash": float(a["cash"]),
                "portfolio_value": float(a["portfolio_value"]),
                "buying_power": float(a["buying_power"]),
                "status": a["status"],
            }
    except: pass
    return None

def get_positions():
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/positions", headers=HEADERS, timeout=10)
        if r.status_code==200: return r.json()
    except: pass
    return []

def get_pending_orders():
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/orders?status=all&limit=50", headers=HEADERS, timeout=10)
        if r.status_code==200:
            orders = r.json()
            return [o for o in orders if o["status"] in ("accepted","new","partially_filled")]
    except: pass
    return []

def place_order(symbol, qty, side, order_type="market", limit_price=None):
    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": "day"
    }
    if limit_price:
        payload["limit_price"] = str(limit_price)
    try:
        r = requests.post(f"{ALPACA_BASE}/v2/orders", json=payload, headers=HEADERS, timeout=15)
        if r.status_code in (200,201):
            o = r.json()
            return {"success": True, "order_id": o["id"], "symbol": symbol,
                    "side": side, "qty": qty, "status": o["status"]}
        else:
            return {"success": False, "symbol": symbol, "error": r.text}
    except Exception as e:
        return {"success": False, "symbol": symbol, "error": str(e)}

def cancel_order(order_id):
    try:
        r = requests.delete(f"{ALPACA_BASE}/v2/orders/{order_id}", headers=HEADERS, timeout=10)
        return r.status_code in (200,204)
    except: return False

# ── Quote Fetcher ────────────────────────────────────────────────────────────
def fetch_quote(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval":"1d","range":"5d"}
        r = requests.get(url, params=params, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        data = r.json()
        meta = data["chart"]["result"][0]["meta"]
        return {
            "symbol": symbol,
            "currentPrice": meta.get("regularMarketPrice",0),
            "prevClose": meta.get("previousClose",0),
            "dayHigh": meta.get("dayHigh",0),
            "dayLow": meta.get("dayLow",0),
            "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh",0),
            "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow",0),
            "marketCap": meta.get("marketCap",0),
            "change": meta.get("regularMarketChange",0),
            "changePct": meta.get("regularMarketChangePercent",0),
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

# ── Scoring Engine ────────────────────────────────────────────────────────────
def score_stock(q, cal_ctx=None, fed_regime=None):
    """Score a stock. Returns (score, signals)."""
    if cal_ctx is None: cal_ctx = CAL_CTX
    if fed_regime is None: fed_regime = FED_REGIME

    score = 0; signals = []
    try:
        cp = q["currentPrice"]; high52 = q["fiftyTwoWeekHigh"]; low52 = q["fiftyTwoWeekLow"]
        pct_from_high = ((cp-high52)/high52*100) if high52 else 0
        pct_from_low  = ((cp-low52) /low52*100)  if low52  else 0
        chg_day = q.get("change",0); chg_pct = q.get("changePct",0)
        sym = q["symbol"]
        pressure = cal_ctx["calendar_pressure"]
        regime = fed_regime.get("regime","unknown")
        ten_yr = fed_regime.get("ten_year")

        # Calendar adjustments
        if cal_ctx["in_fomc_week"]:
            beta = q.get("beta",1.0)
            if beta and beta>1.3:   score-=0.5; signals.append("⚠️ FOMC: high beta")
            elif beta and beta<0.9: score+=0.3; signals.append("🛡️ FOMC: defensive low beta")

        if cal_ctx["in_earnings_season"]:
            earn_sens=["NFLX","AMZN","GOOGL","META","NVDA","AMD","BAC","JPM","GS","C","MS","XLF","XLK"]
            if sym in earn_sens: score-=0.5; signals.append("⚠️ Earnings season: high-revision-risk")
            else:               score+=0.2; signals.append("✅ Earnings season: stable name")

        if cal_ctx["in_cpi_week"] or cal_ctx["is_employment_friday"]:
            macro_def=["XLU","VNQ","XLP","VYM","GLD","IAU","KO"]
            if sym in macro_def:  score+=0.4; signals.append("🛡️ Macro week: defensive")
            elif chg_day>2:       score-=0.2; signals.append("⚠️ Macro week: momentum fade")

        if cal_ctx["in_pension_rebalance"]:
            if pct_from_high>=-5: score+=0.3; signals.append("💼 Pension rebalance: near 52w high")
            else:                 score-=0.2; signals.append("⚠️ Pension flow: lower conviction")

        # Fed regime adjustments
        if ten_yr and ("VERY_TIGHT" in regime or "RESTRICTIVE" in regime):
            pe = q.get("trailingPE",0) or 0
            if pe and pe>30:    score-=0.5; signals.append(f"⚠️ Tight rates: high P/E ({pe:.0f})")
            elif pe and pe<20:  score+=0.3; signals.append(f"✅ Tight rates: value (P/E {pe:.0f})")
            banks=["BAC","JPM","GS","C","MS","KEY","MTB","USB"]
            if sym in banks:   score+=0.4; signals.append("🏦 Tight rates: bank spread")
            rate_sens=["XLU","VNQ","IYR","XLRE","SKT","SPG"]
            if sym in rate_sens: score-=0.5; signals.append("⚠️ Tight rates: rate-sensitive")

        if ten_yr and "ACCOMMODATIVE" in regime:
            pe = q.get("trailingPE",0) or 0
            if pe and pe>25:   score+=0.4; signals.append("✅ Low rates: growth P/E expansion")
            rate_sens=["XLU","VNQ","IYR","XLRE"]
            if sym in rate_sens: score+=0.4; signals.append("✅ Low rates: utilities/REITs")

        rd = fed_regime.get("rate_direction","neutral")
        if rd == "RISING 📈":
            if pct_from_high>=-10: score+=0.2; signals.append("📈 Rising yields: 52w high holds")
            else:                  score-=0.3; signals.append("📉 Rising yields: deep pullback")
        elif rd == "FALLING 📉":
            if chg_day>1: score+=0.3; signals.append("📈 Falling yields: growth momentum")

        # Quantitative rules
        if pct_from_high>=-3:  score+=1.0; signals.append(f"within 3% of 52w high (${cp:.2f})")
        elif pct_from_low>=80: score-=0.5; signals.append(f"{pct_from_low:.0f}% above 52w low — OVERBOUGHT, penalised")
        elif pct_from_low>=40: signals.append(f"{pct_from_low:.0f}% above 52w low — near range, no score boost")

        if abs(chg_day)<1.5 and pct_from_high>-5:
            score+=0.5; signals.append("low vol / defensive positioning")

        # Fundamental rules
        if sym=="AAPL" and pct_from_high>=-5:  score+=1.5; signals.append("AAPL: 52w high, AI phone cycle")
        elif sym=="GOOGL" and pct_from_high>=-10: score+=1.5; signals.append("GOOGL: cheap mega-cap AI")
        elif sym=="V" and pct_from_high>-7:   score+=1.0; signals.append("V: network effect, cross-border")
        elif sym=="LLY":                       score+=1.0; signals.append("LLY: GLP-1 monopoly")

        # Opportunistic
        if sym=="INTC" and chg_pct<5:          score+=1.5; signals.append(f"INTC: turnaround +{chg_pct:.1f}%")
        elif sym=="SOXX" and pct_from_low>=20: score+=1.0; signals.append(f"SOXX: semis +{pct_from_low:.0f}% from low")

        if sym=="XLE":                         score+=0.5; signals.append("XLE: oil, OPEC+ discipline")
        elif sym=="CVX" and pct_from_high>-15: score+=0.5; signals.append("CVX: dip buy candidate")

        if sym in ("SOXX","NVDA","XLK"):      score+=0.5; signals.append(f"{sym}: CHIPS Act AI beneficiary")

        # Momentum filter
        if chg_day>2:   score+=0.5; signals.append(f"+{chg_day:.1f}% today — momentum")
        elif chg_day<-2: score-=0.5; signals.append(f"{chg_day:.1f}% today — weakness")

    except Exception as e:
        signals.append(f"scoring error: {e}")

    return score, signals

# ── Normalize raw scores to 0-100 scale ──────────────────────────────────────
def normalize_scores(raw_score, all_scores, min_scale=20, max_scale=95):
    """
    Map raw scores (roughly -3 to +5) to a 0-100 scale.
    Best candidate gets max_scale (95), worst positive gets min_scale (20),
    negatives get 0. Scaled by relative ranking.
    """
    positive = [s for s in all_scores if s > 0]
    if not positive:
        return 0
    mn, mx = min(positive), max(positive)
    if mx == mn:
        normalized = (raw_score / mx * max_scale) if mx > 0 else 0
    else:
        normalized = ((raw_score - mn) / (mx - mn)) * (max_scale - min_scale) + min_scale
    return max(0, min(100, round(normalized)))

# ── Position Sizing — Weighted by Score ─────────────────────────────────────
def calc_position_size_weighted(account, price, score, all_scores):
    """
    Size position proportionally to score relative to all scored candidates.
    score: float — this stock's score
    all_scores: list[float] — scores of all candidate stocks in this run
    portfolio_fraction: how much of portfolio to allocate across all positions (default 0.80)
    """
    pv = float(account["portfolio_value"])
    total_score = sum(max(s, 0) for s in all_scores)  # ignore negatives
    if total_score == 0:
        return max(1, int(100 / price))
    weight = max(score, 0) / total_score
    portfolio_fraction = 0.80
    max_dollar = pv * portfolio_fraction * weight
    qty = int(max_dollar / price)
    if qty * price < 100:
        qty = max(1, int(100 / price))
    return qty

def calc_position_size(account, price, max_pct=0.10):
    """Fallback: size at max_pct of portfolio, min $100"""
    pv = account["portfolio_value"]
    max_dollar = pv * max_pct
    qty = int(max_dollar / price)
    if qty * price < 100:
        qty = max(1, int(100 / price))
    return qty

# ── Core Trading Logic ────────────────────────────────────────────────────────
MAX_POSITIONS = 20      # max open positions
MAX_ORDERS    = 5       # max new orders per run
MAX_PCT_PORT  = 0.12    # max % of portfolio in any single position
STOP_LOSS_PCT = 0.05    # 5% stop-loss on positions
TARGET_PCT    = 0.08    # target gain before taking profits
ROTATION_THRESHOLD = 1.0 # min score advantage to trigger rotation (candidate must beat worst position by this much)

def run_trade_cycle():
    """
    Full trading cycle:
    1. Check if market is open
    2. Get account + positions + pending orders
    3. Fetch quotes + score watchlist
    4. Exit logic: stop-loss / take-profit on existing positions
    5. Entry logic: new BUY signals from scoring
    6. Cancel stale pending orders
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M ET")
    log = [f"\n{'='*60}",
           f"🤖 AUTO-TRADE CYCLE — {ts}",
           f"{'='*60}"]

    if not is_market_open():
        log.append("⏰ Market closed — cycle skipped")
        return "\n".join(log)

    log.append(f"🏦 Fed: {FED_REGIME.get('ten_year','?')}% | {FED_REGIME.get('regime','?')} | {FED_REGIME.get('rate_direction','?')}")
    if CAL_CTX["active_windows"]:
        log.append(f"📅 Calendar: {', '.join(CAL_CTX['active_windows'])}")

    # ── Step 1: Account & Positions ───────────────────────────────────────────
    account = get_account()
    if not account:
        log.append("❌ Could not fetch account — aborting"); return "\n".join(log)

    pv = account["portfolio_value"]
    cash = account["cash"]
    positions = get_positions()
    pending = get_pending_orders()

    log.append(f"\n💵 Cash: ${cash:,.2f} | Portfolio: ${pv:,.2f}")
    log.append(f"📊 Open positions: {len(positions)} | Pending orders: {len(pending)}")

    # ── Step 2: Fetch quotes & score ───────────────────────────────────────────
    quotes = []
    for sym in WATCHLIST:
        q = fetch_quote(sym)
        quotes.append(q)
        time.sleep(0.15)

    scored = []
    for q in quotes:
        if "error" in q: continue
        score, signals = score_stock(q, CAL_CTX, FED_REGIME)
        scored.append({**q, "score": score, "signals": signals})

    # ── Step 2b: Merge ETF/crypto BUY signals from portfolio DB ─────────────────
    db_signals = get_db_signals(min_score=60, limit=20)
    if db_signals:
        db_syms = {s["symbol"] for s in db_signals}
        already_scored = {s["symbol"] for s in scored}
        new_syms = db_syms - already_scored
        if new_syms:
            log.append(f"\n📊 Fetching {len(new_syms)} DB signals not in WATCHLIST: {', '.join(sorted(new_syms))}")
        for sig in db_signals:
            sym = sig["symbol"]
            if sym in already_scored:
                continue  # already scored via WATCHLIST
            q = fetch_quote(sym)
            if q and "error" not in q:
                score, signals = score_stock(q, CAL_CTX, FED_REGIME)
                # Apply DB signal score as a multiplier so portfolio_manager conviction feeds through
                db_boost = sig["db_score"] / 100.0
                score = score * db_boost
                scored.append({**q, "score": score, "signals": signals + [f"📈 DB signal score={sig['db_score']:.0f}"]})
                time.sleep(0.15)
            else:
                log.append(f"  ⚠️ {sym} in DB signals but no quote available")

    scored.sort(key=lambda x: x["score"], reverse=True)

    buy_candidates  = [s for s in scored if s["score"]>=1.0]
    hold_candidates = [s for s in scored if 0<=s["score"]<1.0]

    log.append(f"\n🔍 Top signals (raw → 0-100):")
    scored_with_norm = [(s, normalize_scores(s["score"], [x["score"] for x in scored])) for s in scored[:5]]
    for s, norm in scored_with_norm:
        log.append(f"  {'✅' if s['score']>=1 else '🟡' if s['score']>=0 else '🔴'} {s['symbol']}: raw={s['score']:.1f} → {norm}/100 | {s['signals'][0] if s['signals'] else 'no signal'}")

    actions_taken = []

    # ── Step 3: Exit Logic — Stop-Loss & Take-Profit ─────────────────────────
    log.append(f"\n🔚 EXIT CHECK:")
    for p in positions:
        sym = p["symbol"]
        qty = float(p["qty"])
        avg = float(p["current_price"])  # current price from Alpaca
        # Get real-time price
        match_q = next((q for q in quotes if q["symbol"]==sym), None)
        if not match_q: continue
        cp = match_q["currentPrice"]
        entry = float(p["avg_entry_price"])
        pl_pct = (cp - entry) / entry if entry else 0
        pl_pct_val = pl_pct * 100

        exited = False

        # Stop-loss: -5%
        if pl_pct <= -STOP_LOSS_PCT:
            log.append(f"  🛑 STOP-LOSS: {sym} at ${cp:.2f} ({pl_pct_val:.1f}%) — selling {qty} shares")
            result = place_order(sym, int(qty), "sell")
            if result.get("success"):
                actions_taken.append(f"SELL {sym} (stop-loss {pl_pct_val:.1f}%)")
                log.append(f"    → Order placed: {result}")
            else:
                log.append(f"    → FAILED: {result.get('error')}")
            exited = True

        # Take-profit: +8%
        elif pl_pct >= TARGET_PCT:
            log.append(f"  🎯 TAKE-PROFIT: {sym} at ${cp:.2f} ({pl_pct_val:.1f}%) — selling {qty} shares")
            result = place_order(sym, int(qty), "sell")
            if result.get("success"):
                actions_taken.append(f"SELL {sym} (take-profit {pl_pct_val:.1f}%)")
                log.append(f"    → Order placed: {result}")
            else:
                log.append(f"    → FAILED: {result.get('error')}")
            exited = True

        # Emergency exit: down 2% on a high-conviction name in FOMC week
        if not exited and CAL_CTX["in_fomc_week"] and pl_pct <= -0.02:
            beta = match_q.get("beta",1.0) or 1.0
            if beta > 1.3:
                log.append(f"  ⚠️ FOMC EXIT: {sym} high-beta ({beta:.1f}), {pl_pct_val:.1f}% — trimming half")
                half_qty = max(1, int(qty/2))
                result = place_order(sym, half_qty, "sell")
                if result.get("success"):
                    actions_taken.append(f"SELL {sym} (FOMC risk-reduce half)")
                    log.append(f"    → Order placed: {result}")

    # ── Step 3b: Compute available slots before exits alter position count ───────
    open_syms = {p["symbol"] for p in positions}
    pending_buys = {o["symbol"] for o in pending if o["side"]=="buy"}
    slots_available = MAX_POSITIONS - len(positions) - len(pending_buys)

    # ── Step 4: Rotation — swap low-scored positions for better candidates ─────
    log.append(f"\n🔄 ROTATION CHECK:")
    if slots_available <= 0 and buy_candidates:
        # Score existing positions (approximate, using same engine)
        scored_positions = []
        for p in positions:
            match_q = next((q for q in quotes if q["symbol"]==p["symbol"]), None)
            if match_q and "error" not in match_q:
                score, _ = score_stock(match_q, CAL_CTX, FED_REGIME)
                entry = float(p["avg_entry_price"])
                cp = match_q["currentPrice"]
                pl_pct = (cp - entry) / entry if entry else 0
            else:
                score = 0
                pl_pct = 0
            scored_positions.append({**p, "score": score, "pl_pct": pl_pct})

        scored_positions.sort(key=lambda x: x["score"])
        worst = scored_positions[0]
        best_candidate = buy_candidates[0]

        if best_candidate["score"] - worst["score"] >= ROTATION_THRESHOLD:
            log.append(f"  🔁 ROTATING: {worst['symbol']} (score={worst['score']:.1f}, {worst['pl_pct']*100:.1f}%) → {best_candidate['symbol']} (score={best_candidate['score']:.1f})")
            qty = int(float(worst["qty"]))
            result = place_order(worst["symbol"], qty, "sell")
            if result.get("success"):
                actions_taken.append(f"ROTATE OUT {worst['symbol']}")
                # Record rotation sell in signals table so engine can't re-buy immediately
                try:
                    db_path = os.path.expanduser("~/.hermes/cron/output/wealth/portfolio.db")
                    conn_rot = sqlite3.connect(db_path)
                    conn_rot.execute("""
                        INSERT INTO signals (symbol, signal_date, signal_type, trigger_rule,
                        trigger_detail, score_before, price_at_signal, conviction, status)
                        VALUES (?, ?, 'sell', 'auto_trade_rotation',
                        'Rotated out by engine — portfolio manager controls re-entry', ?, ?, 'high', 'active')
                    """, (worst["symbol"], datetime.now().strftime("%Y-%m-%d"),
                          worst["score"], worst.get("current_price", 0)))
                    conn_rot.commit()
                    conn_rot.close()
                except Exception:
                    pass  # don't fail the trade if DB write fails
                log.append(f"    → Sold {qty} shares @ ${worst.get('current_price', '?')}")
                slots_available = 1
            else:
                log.append(f"    → Failed to sell {worst['symbol']}: {result.get('error')}")
        else:
            log.append(f"  ⏭️ No rotation: best candidate {best_candidate['symbol']} ({best_candidate['score']:.1f}) vs worst position {worst['symbol']} ({worst['score']:.1f}) — gap {best_candidate['score']-worst['score']:.1f} < threshold {ROTATION_THRESHOLD}")

    # ── Step 5: Cancel Stale Orders ──────────────────────────────────────────
    log.append(f"\n📋 ORDER CLEANUP:")
    for o in pending:
        age_mins = (datetime.now() - datetime.fromisoformat(o["created_at"].replace("Z",""))).total_seconds()/60
        if age_mins > 60:
            log.append(f"  🗑️ Cancelling stale order: {o['symbol']} {o['side']} {o['qty']} (age: {age_mins:.0f}min)")
            if cancel_order(o["id"]):
                actions_taken.append(f"CANCEL {o['symbol']}")
            else:
                log.append(f"    → Failed to cancel")

    # ── Step 6: Entry Logic — New Buys ───────────────────────────────────────
    log.append(f"\n🚀 ENTRY CHECK:")

    # Re-check available slots (rotation sell may have been placed)
    open_syms = {p["symbol"] for p in positions}
    pending_buys = {o["symbol"] for o in pending if o["side"]=="buy"}
    slots_available = MAX_POSITIONS - len(positions) - len(pending_buys)

    log.append(f"  Slots available: {slots_available} (max {MAX_POSITIONS} positions, {len(positions)} open, {len(pending_buys)} pending)")
    log.append(f"  Slots available: {slots_available} (max {MAX_POSITIONS} positions, {len(positions)} open, {len(pending_buys)} pending)")

    # ── Step 6b: Get portfolio-manager rotated symbols ──────────────────────
    # The portfolio manager (check_signals) rotates out symbols when composite score < 40.
    # The day trading engine should NOT re-buy those symbols on momentum — only the
    # portfolio manager can signal re-entry. This prevents the conflict where the
    # portfolio manager sells at $106 (earnings quality collapse) and the engine
    # immediately buys at $109 (momentum bounce).
    rotated_syms = set()
    try:
        db_path = os.path.expanduser("~/.hermes/cron/output/wealth/portfolio.db")
        conn_rot = sqlite3.connect(db_path)
        cutoff = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        rows = conn_rot.execute(
            "SELECT symbol FROM signals WHERE signal_type='sell' AND status='active' AND signal_date >= ?",
            (cutoff,)).fetchall()
        rotated_syms = {r["symbol"] for r in rows}
        conn_rot.close()
    except Exception:
        pass  # don't block trades if DB check fails

    if slots_available <= 0:
        log.append("  ⏭️ Max positions reached — no new entries")
    else:
        if rotated_syms:
            log.append(f"  🚫 Portfolio manager rotated: {sorted(rotated_syms)}")

        new_buys = 0
        scored_symbols = [s for s in scored if s["score"] > 0]
        all_scores = [s["score"] for s in scored_symbols]
        total_score = sum(all_scores)

        for cand in buy_candidates:
            if new_buys >= min(slots_available, MAX_ORDERS):
                break
            sym = cand["symbol"]
            if sym in open_syms or sym in pending_buys:
                log.append(f"  ⏭️ {sym} already have/pending — skipped"); continue
            if sym in rotated_syms:
                log.append(f"  🚫 {sym} in portfolio manager rotation list — skip momentum buy"); continue
            if cand["currentPrice"] == 0:
                log.append(f"  ⏭️ {sym} no price data — skipped"); continue

            qty = calc_position_size_weighted(account, cand["currentPrice"], cand["score"], all_scores)
            if qty < 1: qty = 1

            log.append(f"  ✅ BUY SIGNAL: {sym} score={cand['score']:.1f} @ ${cand['currentPrice']:.2f} — {qty} shares (${qty*cand['currentPrice']:.2f})")
            log.append(f"     Signals: {' | '.join(cand['signals'][:3])}")

            result = place_order(sym, qty, "buy")
            if result.get("success"):
                new_buys += 1
                actions_taken.append(f"BUY {sym} {qty} shares")
                log.append(f"    → Order placed: {result['order_id']} [{result['status']}]")
            else:
                log.append(f"    → FAILED: {result.get('error')}")

    # ── Summary ───────────────────────────────────────────────────────────────
    log.append(f"\n{'='*60}")
    log.append(f"✅ Cycle complete at {ts}")
    log.append(f"   Actions: {len(actions_taken)} — {', '.join(actions_taken) if actions_taken else 'none'}")
    log.append(f"   Cash: ${cash:,.2f} | Portfolio: ${pv:,.2f}")

    return "\n".join(log)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    output_dir = os.path.expanduser("~/.hermes/cron/output/wealth")
    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, "auto_trade_log.txt")

    report = run_trade_cycle()
    print(report)

    with open(out_file,"w") as f:
        f.write(report)

    # Also write compact JSON for dashboard
    compact = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M ET"),
        "report": report,
        "fed_regime": FED_REGIME,
        "calendar_context": CAL_CTX,
    }
    json_file = os.path.join(output_dir, "auto_trade_latest.json")
    with open(json_file,"w") as f:
        json.dump(compact, f, indent=2)