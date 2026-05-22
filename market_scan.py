#!/usr/local/bin/python3
"""
Market Intelligence Scanner — Alex Yu
Hourly during trading hours (9:30 AM–4:00 PM ET, Mon–Fri)
Scans watchlist against 6 strategic rules + calendar context.
"""
import os, sys, json, time, requests
from datetime import datetime

API_KEY = os.environ.get("ALPACA_API_KEY", "PKYBN34XEJMJA46ZVPNIALRKIP")
API_SECRET = os.environ.get("ALPACA_API_SECRET", "Bw6TbtEaZN6zSeLBGd2NZiWHijiSi7GHD4fgtzb5hvoA")
ALPACA_BASE = "https://paper-api.alpaca.markets"
HEADERS = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": API_SECRET}

WATCHLIST = ["AAPL", "GOOGL", "QQQ", "V", "XLE", "SOXX", "KO", "CVX", "LLY", "INTC", "SPY", "NVDA", "AMZN", "META", "MSFT"]
OUTPUT_FILE = os.path.expanduser("~/.hermes/cron/output/wealth/market_scan.json")

# ── Calendar Engine ────────────────────────────────────────────────────────────
FOMC_WINDOWS = [
    (1, 28, 31), (3, 17, 20), (5, 5, 8), (6, 16, 19),
    (7, 28, 31), (9, 16, 19), (10, 6, 9), (12, 15, 18),
]
EARNINGS_SEASONS = [
    (1, 8, 21), (4, 8, 21), (7, 8, 21), (10, 8, 21),
]
ECON_RELEASE_WINDOWS = [
    (1, 5, 12), (2, 5, 12), (3, 5, 12), (4, 5, 12),
    (5, 5, 12), (6, 5, 12), (7, 5, 12), (8, 5, 12),
    (9, 5, 12), (10, 5, 12), (11, 5, 12), (12, 5, 12),
]

def get_calendar_context():
    now = datetime.now()
    month = now.month
    day = now.day
    weekday = now.weekday()

    in_earnings_season = any(m == month and s <= day <= e for m, s, e in EARNINGS_SEASONS)
    in_fomc_week = any(m == month and (d - 2) <= day <= (d + 2) for m, d, e in FOMC_WINDOWS)
    in_macro_week = any(m == month and s <= day <= e for m, s, e in ECON_RELEASE_WINDOWS)
    in_cpi_week = 8 <= day <= 14
    is_employment_friday = weekday == 4 and 1 <= day <= 14
    in_pension_rebalance = day >= 25 and weekday < 5
    is_quarter_end = month in [3, 6, 9, 12] and day >= 25
    is_year_end = month == 12 and day >= 20
    is_january = month == 1

    pressure = 0.0
    if in_earnings_season: pressure += 0.25
    if in_fomc_week: pressure += 0.30
    if in_macro_week: pressure += 0.15
    if in_pension_rebalance: pressure += 0.10
    if is_year_end: pressure += 0.15
    if is_quarter_end: pressure += 0.05

    return {
        "in_earnings_season": in_earnings_season,
        "in_fomc_week": in_fomc_week,
        "in_macro_week": in_macro_week,
        "in_cpi_week": in_cpi_week,
        "is_employment_friday": is_employment_friday,
        "in_pension_rebalance": in_pension_rebalance,
        "is_quarter_end": is_quarter_end,
        "is_year_end": is_year_end,
        "is_january": is_january,
        "calendar_pressure": min(1.0, pressure),
        "month": month,
        "day": day,
    }

CAL_CTX = get_calendar_context()

# ── Fed Rate Monitor ─────────────────────────────────────────────────────────
# Live 10Y Treasury yield from Yahoo Finance as Fed policy regime proxy
# Regime logic: fed funds ~5.25-5.50% ceiling as of May 2026
# 10Y > 4.5% = restrictive territory, < 3.5% = accommodative

def get_fed_regime():
    """
    Fetch current 10Y Treasury yield and determine rate regime + slope.
    Also compute days-to-next-FOMC from known windows.
    Returns a dict with live rate data and regime assessment.
    """
    import yfinance as yf

    rate_data = {
        "ten_year": None,
        "two_year": None,
        "spread_10y2y": None,
        "regime": "unknown",  # ACCOMMODATIVE / NEUTRAL / RESTRICTIVE / VERY_TIGHT
        "rate_direction": "neutral",  # RISING / FALLING / NEUTRAL
        "fomc_countdown": None,
        "minutes_until_fomc": None,
        "fed_watch": "🟡 neutral",
        "last_updated": None,
    }

    try:
        # Fetch 10Y and 2Y yields
        fi_10 = yf.Ticker("^TNX").fast_info
        fi_2 = yf.Ticker("^FVX").fast_info  # 5Y as proxy for 2Y (more reliable)

        ten_yr = getattr(fi_10, "last_price", None)
        two_yr = getattr(fi_2, "last_price", None)  # using 5Y as proxy

        if ten_yr:
            rate_data["ten_year"] = round(float(ten_yr), 3)
        if two_yr:
            rate_data["two_year"] = round(float(two_yr), 3)

        if ten_yr and two_yr:
            rate_data["spread_10y2y"] = round(float(ten_yr) - float(two_yr), 3)

            # Regime classification (based on 10Y yield level)
            if ten_yr > 5.0:
                rate_data["regime"] = "VERY_TIGHT 🔴"
                rate_data["fed_watch"] = "🔴 VERY TIGHT — HIGH BORROWING COST"
            elif ten_yr > 4.5:
                rate_data["regime"] = "RESTRICTIVE 🟠"
                rate_data["fed_watch"] = "🟠 RESTRICTIVE — elevated rates"
            elif ten_yr > 3.5:
                rate_data["regime"] = "NEUTRAL 🟡"
                rate_data["fed_watch"] = "🟡 NEUTRAL — balanced policy"
            else:
                rate_data["regime"] = "ACCOMMODATIVE 🟢"
                rate_data["fed_watch"] = "🟢 ACCOMMODATIVE — low rates"

            # Rate direction: compare 10Y to its 30-day moving average
            # (simplified: use 30-day historical data via yfinance history)
            try:
                t = yf.Ticker("^TNX")
                hist = t.history(period="1mo", interval="1d")
                if hist is not None and len(hist) >= 5:
                    ma30 = hist["Close"].mean()
                    if ten_yr > ma30 * 1.01:
                        rate_data["rate_direction"] = "RISING 📈"
                        rate_data["fed_watch"] += " | 📈 yields rising"
                    elif ten_yr < ma30 * 0.99:
                        rate_data["rate_direction"] = "FALLING 📉"
                        rate_data["fed_watch"] += " | 📉 yields falling"
                    else:
                        rate_data["rate_direction"] = "STABLE ➡️"
                        rate_data["fed_watch"] += " | ➡️ stable"
            except Exception:
                pass

        rate_data["last_updated"] = datetime.now().strftime("%H:%M ET")

    except Exception as e:
        rate_data["fed_watch"] = f"⚠️ rate data unavailable: {e}"

    # ── FOMC Countdown ─────────────────────────────────────────────────────
    now = datetime.now()
    month = now.month
    day = now.day
    year = now.year

    # Find next FOMC meeting
    next_fomc = None
    for m, d_start, d_end in FOMC_WINDOWS:
        if m >= month:
            # Find the first day of the window as the meeting start
            fomc_date = datetime(year, m, d_start)
            if fomc_date >= now:
                next_fomc = fomc_date
                break

    if next_fomc:
        delta = next_fomc - now
        rate_data["fomc_countdown"] = delta.days
        rate_data["minutes_until_fomc"] = delta.days * 24 * 60
        rate_data["next_fomc_date"] = next_fomc.strftime("%b %d")
        rate_data["fed_watch"] += f" | FOMC in {delta.days}d ({next_fomc.strftime('%b %d')})"
    else:
        rate_data["fomc_countdown"] = 0
        rate_data["minutes_until_fomc"] = 0
        rate_data["next_fomc_date"] = "unknown"
        rate_data["fed_watch"] += " | FOMC date unknown"

    return rate_data

FED_REGIME = get_fed_regime()


def is_market_open():
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/clock", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json().get("is_open", False)
    except Exception:
        pass
    now = datetime.utcnow()
    et_hour = (now.hour - 4) % 24
    et_weekday = now.weekday()
    return 9 <= et_hour < 16 and et_weekday < 5

def fetch_quote(symbol):
    """Fetch real-time quote from Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1d", "range": "5d"}
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        meta = data["chart"]["result"][0]["meta"]
        return {
            "symbol": symbol,
            "currentPrice": meta.get("regularMarketPrice", 0),
            "prevClose": meta.get("previousClose", 0),
            "dayHigh": meta.get("dayHigh", 0),
            "dayLow": meta.get("dayLow", 0),
            "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh", 0),
            "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow", 0),
            "marketCap": meta.get("marketCap", 0),
            "change": meta.get("regularMarketChange", 0),
            "changePct": meta.get("regularMarketChangePercent", 0),
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

def get_alpaca_account():
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/account", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            a = r.json()
            return {
                "cash": float(a["cash"]),
                "portfolioValue": float(a["portfolio_value"]),
                "buyingPower": float(a["buying_power"]),
                "status": a["status"],
            }
    except:
        pass
    return None

def get_alpaca_orders():
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/orders?status=all&limit=20", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return []

def get_alpaca_positions():
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/positions", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return []

def score_stock(q, cal_ctx=None, fed_regime=None):
    """Score stock against 6 strategic rules + calendar + Fed regime. Returns (score, signals)."""
    if cal_ctx is None:
        cal_ctx = CAL_CTX
    if fed_regime is None:
        fed_regime = FED_REGIME

    score = 0
    signals = []

    try:
        cp = q["currentPrice"]
        high52 = q["fiftyTwoWeekHigh"]
        low52 = q["fiftyTwoWeekLow"]
        pct_from_high = ((cp - high52) / high52 * 100) if high52 else 0
        pct_from_low = ((cp - low52) / low52 * 100) if low52 else 0
        chg = q.get("changePct", 0)
        chg_day = q.get("change", 0)

        sym = q["symbol"]
        pressure = cal_ctx["calendar_pressure"]
        regime = fed_regime.get("regime", "unknown")
        ten_yr = fed_regime.get("ten_year")
        rate_dir = fed_regime.get("rate_direction", "neutral")

        # ── Rule 6: Calendar Pressure Adjustments ──────────────────────────
        # Adjust base conviction during high-volatility windows
        if cal_ctx["in_fomc_week"]:
            # Fed week: be cautious on high-beta names, reward low-beta
            beta = q.get("beta", 1.0)
            if beta and beta > 1.3:
                score -= 0.5
                signals.append(f"⚠️ FOMC week: high beta ({beta:.1f}) — caution")
            elif beta and beta < 0.9:
                score += 0.3
                signals.append(f"🛡️ FOMC week: defensive low beta ({beta:.1f})")

        if cal_ctx["in_earnings_season"]:
            # Earnings season: high-exposure tech/financials penalized
            earn_sens = ["NFLX", "AMZN", "GOOGL", "META", "NVDA", "AMD",
                         "BAC", "JPM", "GS", "C", "MS", "XLF", "XLK"]
            if sym in earn_sens:
                score -= 0.5
                signals.append("⚠️ Earnings season: high-revision-risk name")
            else:
                score += 0.2
                signals.append("✅ Earnings season: stable-revision name")

        if cal_ctx["in_cpi_week"] or cal_ctx["is_employment_friday"]:
            # Macro data week: defensive names rewarded
            macro_def = ["XLU", "VNQ", "XLP", "VYM", "GLD", "IAU", "KO"]
            if sym in macro_def:
                score += 0.4
                signals.append("🛡️ Macro week: defensive name scores boost")
            elif chg_day > 2:
                score -= 0.2
                signals.append("⚠️ Macro week: momentum faded by data uncertainty")

        if cal_ctx["in_pension_rebalance"]:
            # Pension rebalance: favor liquid, large-cap
            if pct_from_high >= -5:
                score += 0.3
                signals.append("💼 Pension rebalance: near 52w high = institutional quality")
            else:
                score -= 0.2
                signals.append("⚠️ Pension flow: lower conviction in thin name")

        if cal_ctx["is_year_end"]:
            # Year-end: small caps and cyclicals get boost
            if pct_from_low >= 30:
                score += 0.5
                signals.append("📈 Year-end: small cap momentum")

        # ── Fed Rate Regime Adjustments ────────────────────────────────────
        # Rule 7: Fed rate regime modulates valuations and sector performance
        if ten_yr:
            # VERY TIGHT (>5.0%): penalize long-duration growth, reward value/short duration
            if "VERY_TIGHT" in regime or "RESTRICTIVE" in regime:
                # Growth stocks (high P/E) get hit in tight rate environment
                pe = q.get("trailingPE", 0) or 0
                if pe and pe > 30:
                    score -= 0.5
                    signals.append(f"⚠️ Tight rates: high P/E ({pe:.0f}) penalized")
                elif pe and pe < 20:
                    score += 0.3
                    signals.append(f"✅ Tight rates: value stock (P/E {pe:.0f}) scores")

                # Banks benefit from steep yield curve
                if sym in ["BAC", "JPM", "GS", "C", "MS", "KEY", "MTB", "USB"]:
                    score += 0.4
                    signals.append("🏦 Tight rates: bank spread widening")

                # Rate-sensitive sectors: utilities, REITs hurt
                rate_sens = ["XLU", "VNQ", "IYR", "XLRE", "SKT", "SPG"]
                if sym in rate_sens:
                    score -= 0.5
                    signals.append("⚠️ Tight rates: rate-sensitive REIT/utility hurt")

            # ACCOMMODATIVE (<3.5%): growth stocks benefit, utilities/reits boosted
            elif "ACCOMMODATIVE" in regime:
                if pe and pe > 25:
                    score += 0.4
                    signals.append("✅ Low rates: growth P/E expansion")
                if sym in rate_sens:
                    score += 0.4
                    signals.append("✅ Low rates: utilities/REITs benefit")

            # Rising yields: short-duration assets outperform
            if rate_dir == "RISING 📈":
                if pct_from_high >= -10:
                    score += 0.2
                    signals.append("📈 Rising yield backdrop: near 52w high holds")
                else:
                    score -= 0.3
                    signals.append("📉 Rising yields: deep pullback — more risk")

            # Falling yields: long-duration growth re-rates higher
            elif rate_dir == "FALLING 📉":
                if chg_day > 1:
                    score += 0.3
                    signals.append("📈 Falling yields: growth momentum intact")

        # ── Rule 5: Quantitative ───────────────────────────────────────────
        # Near 52w high = strong uptrend
        if pct_from_high >= -3:
            score += 1
            signals.append(f"within 3% of 52w high (${cp:.2f} vs ${high52:.2f})")
        elif pct_from_low >= 40:
            score += 0.5
            signals.append(f"+{pct_from_low:.0f}% above 52w low — momentum")

        # Low volatility anchor (KO, V, PG, etc.)
        if abs(chg_day) < 1.5 and pct_from_high > -5:
            score += 0.5
            signals.append("low vol / defensive positioning")

        # ── Rule 1: Fundamental ────────────────────────────────────────────
        if sym == "AAPL" and pct_from_high >= -5:
            score += 1.5
            signals.append("AAPL: 52w high, AI phone cycle, best-in-class balance sheet")
        elif sym == "GOOGL" and pct_from_high >= -10:
            score += 1.5
            signals.append("GOOGL: cheapest mega-cap AI play, Gemini gaining")
        elif sym == "V" and pct_from_high > -7:
            score += 1
            signals.append("V: network effect, cross-border tailwinds")
        elif sym == "LLY":
            score += 1
            signals.append("LLY: GLP-1 monopoly deepening, pipeline strong")

        # ── Rule 2: Opportunistic ───────────────────────────────────────────
        if sym == "INTC" and chg_pct < 5:
            score += 1.5
            signals.append(f"INTC: turnaround narrative active, +{chg_pct:.1f}% today")
        elif sym == "SOXX" and pct_from_low >= 20:
            score += 1
            signals.append(f"SOXX: semiconductor recovery, +{pct_from_low:.0f}% from 52w low")

        # ── Rule 3: Market Event ────────────────────────────────────────────
        if sym == "XLE":
            score += 0.5
            signals.append("XLE: oil stabilizing, OPEC+ discipline, energy under-owned")
        elif sym == "CVX" and pct_from_high > -15:
            score += 0.5
            signals.append("CVX: oil stabilizing, dip buy candidate")

        # ── Rule 4: Politically Aligned ────────────────────────────────────
        if sym in ("SOXX", "NVDA", "XLK"):
            score += 0.5
            signals.append(f"{sym}: CHIPS Act AI infrastructure beneficiary")

        # ── Momentum filter (works for all) ────────────────────────────────
        if chg_day > 2:
            score += 0.5
            signals.append(f"+{chg_day:.1f}% today — intraday momentum")
        elif chg_day < -2:
            score -= 0.5
            signals.append(f"{chg_day:.1f}% today — intraday weakness")

    except Exception as e:
        signals.append(f"scoring error: {e}")

    return score, signals

def generate_report(quotes, account, orders, positions, timestamp, cal_ctx=None, fed_regime=None):
    if cal_ctx is None:
        cal_ctx = CAL_CTX
    if fed_regime is None:
        fed_regime = FED_REGIME

    lines = []
    lines.append(f"📊 MARKET INTELLIGENCE SCAN")
    lines.append(f"🕐 Scanned: {timestamp}")

    # ── Fed Rate Watch Banner ──────────────────────────────────────────────
    tw = fed_regime.get("ten_year")
    regime = fed_regime.get("regime", "unknown")
    countdown = fed_regime.get("fomc_countdown")
    direction = fed_regime.get("rate_direction", "neutral")
    next_fomc = fed_regime.get("next_fomc_date", "?")

    if tw:
        lines.append(f"🏦 FED: 10Y={tw}% | Regime: {regime} | {direction}")
        lines.append(f"   FOMC countdown: {countdown}d ({next_fomc}) | Spread: {fed_regime.get('spread_10y2y', '?')}bp")
    else:
        lines.append(f"🏦 FED: {fed_regime.get('fed_watch', 'data unavailable')}")
    lines.append("")

    # ── Calendar Context Banner ───────────────────────────────────────────
    pressure = cal_ctx["calendar_pressure"]
    active = []
    if cal_ctx["in_fomc_week"]: active.append("FOMC")
    if cal_ctx["in_earnings_season"]: active.append("Earnings Season")
    if cal_ctx["in_macro_week"]: active.append("Macro Week (CPI/Jobs)")
    if cal_ctx["is_employment_friday"]: active.append("Jobs Friday")
    if cal_ctx["in_pension_rebalance"]: active.append("Pension Rebalance")
    if cal_ctx["is_quarter_end"]: active.append("Quarter-End")
    if cal_ctx["is_year_end"]: active.append("Year-End")

    if active:
        pressure_bar = "█" * int(pressure * 10) + "░" * (10 - int(pressure * 10))
        lines.append(f"📅 Calendar: {', '.join(active)} [{pressure_bar}]")
    else:
        lines.append("📅 Calendar: Quiet week")
    lines.append("")

    # Account summary
    if account:
        lines.append(f"💵 Cash: ${account['cash']:,.2f} | Portfolio: ${account['portfolioValue']:,.2f}")
    lines.append("")

    # Positions
    if positions:
        lines.append(f"📈 POSITIONS ({len(positions)}):")
        for p in positions:
            pl_pct = float(p.get("unrealized_plpc", 0)) * 100
            pl = float(p.get("unrealized_pl", 0))
            direction = "🟢" if pl >= 0 else "🔴"
            lines.append(f"  {direction} {p['symbol']}: {p['qty']} shares @ ${float(p['avg_entry_price']):.2f} → ${float(p['current_price']):.2f} | P/L: ${pl:.2f} ({pl_pct:.2f}%)")
        lines.append("")

    # Orders
    if orders:
        pending = [o for o in orders if o["status"] in ("accepted", "new", "partially_filled")]
        if pending:
            lines.append(f"📋 PENDING ORDERS ({len(pending)}):")
            for o in pending:
                lim = f" @ ${float(o['limit_price']):.2f}" if o.get("limit_price") else ""
                filled = "✅ FILLED" if o["status"] == "filled" else "⏳ PENDING"
                lines.append(f"  {o['side'].upper()} {o['qty']} {o['symbol']}{lim} [{o['status']}] {filled}")
            lines.append("")

    # Watchlist scoring
    scored = []
    for q in quotes:
        if "error" in q:
            continue
        score, signals = score_stock(q, CAL_CTX)
        scored.append({**q, "score": score, "signals": signals})

    scored.sort(key=lambda x: x["score"], reverse=True)

    lines.append("🔍 WATCHLIST RANKINGS:")
    lines.append("")
    buy_list = [s for s in scored if s["score"] >= 1]
    hold_list = [s for s in scored if 0 <= s["score"] < 1]
    avoid_list = [s for s in scored if s["score"] < 0]

    if buy_list:
        lines.append("✅ BUY:")
        for s in buy_list:
            cp = s["currentPrice"]
            pct = s.get("changePct", 0)
            sig_str = " | ".join(s["signals"][:3])
            lines.append(f"  {s['symbol']}: ${cp:.2f} ({pct:+.2f}%)")
            if sig_str:
                lines.append(f"    → {sig_str}")

    if hold_list:
        lines.append("\n🟡 HOLD:")
        for s in hold_list:
            cp = s["currentPrice"]
            pct = s.get("changePct", 0)
            sig_str = " | ".join(s["signals"][:2])
            lines.append(f"  {s['symbol']}: ${cp:.2f} ({pct:+.2f}%)")
            if sig_str:
                lines.append(f"    → {sig_str}")

    if avoid_list:
        lines.append("\n🔴 AVOID/WATCH:")
        for s in avoid_list:
            cp = s["currentPrice"]
            pct = s.get("changePct", 0)
            lines.append(f"  {s['symbol']}: ${cp:.2f} ({pct:+.2f}%)")
            lines.append(f"    → {s['signals'][0] if s['signals'] else 'weak signals'}")

    return "\n".join(lines)

def main():
    timestamp = time.strftime("%Y-%m-%d %H:%M ET", time.localtime())

    if not is_market_open():
        msg = f"⏰ Market closed — scan skipped ({timestamp})"
        print(msg)
        # Still write a closed state file
        with open(OUTPUT_FILE, "w") as f:
            json.dump({"status": "closed", "timestamp": timestamp}, f)
        return

    print(f"Running market scan at {timestamp}...")

    # Fetch quotes
    quotes = []
    for sym in WATCHLIST:
        q = fetch_quote(sym)
        quotes.append(q)
        time.sleep(0.15)  # be polite to Yahoo

    # Alpaca data
    account = get_alpaca_account()
    orders = get_alpaca_orders()
    positions = get_alpaca_positions()

    # Generate report
    report = generate_report(quotes, account, orders, positions, timestamp, CAL_CTX, FED_REGIME)

    # Save JSON
    scan_data = {
        "timestamp": timestamp,
        "account": account,
        "positions": positions,
        "orders": orders,
        "quotes": [q for q in quotes if "error" not in q],
        "fed_regime": FED_REGIME,
        "calendar_context": CAL_CTX,
        "report": report,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(scan_data, f, indent=2)

    print(report)
    print(f"\n✅ Scan saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()