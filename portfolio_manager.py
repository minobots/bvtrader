#!/usr/local/bin/python3
"""
Portfolio Manager — Core System
Handles: library queue, scoring, signals, Alpaca orders
Run daily via cron: python3 portfolio_manager.py --run-daily
"""
import sys, os, time, json, sqlite3, requests
from datetime import datetime, date

sys.path.insert(0, "/tmp/mkt_pkg")
DB_PATH = os.path.expanduser("~/.hermes/cron/output/wealth/portfolio.db")

ALPACA_KEY = os.environ.get("ALPACA_API_KEY", "PKYBN34XEJMJA46ZVPNIALRKIP")
ALPACA_SECRET = os.environ.get("ALPACA_API_SECRET", "Bw6TbtEaZN6zSeLBGd2NZiWHijiSi7GHD4fgtzb5hvoA")
ALPACA_BASE = "https://paper-api.alpaca.markets"
HEADERS = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}

TODAY = time.strftime("%Y-%m-%d")
TIMESTAMP = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

# ─────────────────────────────────────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_run(sql, args=()):
    conn = get_db()
    conn.execute(sql, args)
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# CALENDAR ENGINE — temporal context for all scoring and signals
# ─────────────────────────────────────────────────────────────────────────────
from datetime import datetime

# Fed Meeting Windows (FOMC — 8 meetings/year, roughly every 6-8 weeks)
# Market is most volatile in the 5 trading days surrounding a Fed decision
FOMC_WINDOWS = [
    # January
    (1, 28, 31),   # Jan 28-31 (often first meeting)
    # March
    (3, 17, 20),
    # May
    (5, 5, 8),
    # June
    (6, 16, 19),
    # July
    (7, 28, 31),
    # September
    (9, 16, 19),
    # October
    (10, 6, 9),
    # December
    (12, 15, 18),
]

# Earnings Season Windows (2 weeks each, start ~mid-month)
# Jan Q4 (prior year results), Apr Q1, Jul Q2, Oct Q3
EARNINGS_SEASONS = [
    (1, 8, 21),
    (4, 8, 21),
    (7, 8, 21),
    (10, 8, 21),
]

# Monthly Economic Releases (typical release week / days)
# CPI: usually second week of month (Tuesday–Thursday)
# Employment: first Friday of month (or second Friday if holiday)
# PPI, retail sales: second week
ECON_RELEASE_WINDOWS = [
    (1, 5, 12), (2, 5, 12), (3, 5, 12), (4, 5, 12),
    (5, 5, 12), (6, 5, 12), (7, 5, 12), (8, 5, 12),
    (9, 5, 12), (10, 5, 12), (11, 5, 12), (12, 5, 12),
]

# Pension / Fund Rebalancing Windows (last 3 trading days of month)
# Large institutional rebalancing can move sectors predictably
PENSION_REBALANCE_DAYS = [25, 26, 27, 28, 29, 30, 31]

def get_calendar_context():
    """
    Returns a dict of calendar flags that modulate scoring and signals.
    All values are booleans or floats in [0.0, 1.0].
    """
    now = datetime.now()
    month = now.month
    day = now.day
    weekday = now.weekday()  # 0=Mon, 4=Fri
    day_of_year = now.timetuple().tm_yday

    # Week of month: 1-5
    week_of_month = (day - 1) // 7 + 1

    # ── Earnings Season ────────────────────────────────────────────────────
    in_earnings_season = any(
        m == month and s <= day <= e
        for m, s, e in EARNINGS_SEASONS
    )
    earnings_season_score = 1.0 if in_earnings_season else 0.0

    # How many days into current earnings season window (0 = not in season)
    days_into_earnings = 0
    for m, s, e in EARNINGS_SEASONS:
        if m == month and s <= day <= e:
            days_into_earnings = day - s

    # ── Fed / FOMC ─────────────────────────────────────────────────────────
    in_fomc_week = any(
        m == month and (e - 2) <= day <= (e + 1)
        for m, _, e in FOMC_WINDOWS
    )
    # Days to nearest FOMC meeting
    days_to_fomc = 99
    for m, d, e in FOMC_WINDOWS:
        if m == month:
            dist = d - day
            if dist >= 0 and dist < days_to_fomc:
                days_to_fomc = dist
        elif m > month or (m == month and d >= day):
            # Future meeting this year
            pass  # simplified: just check current month

    # General FOMC risk: elevated in the week before any scheduled meeting
    # (Fed gets media coverage, options markets get volatile)
    fomc_risk = 1.0 if in_fomc_week else max(0.0, 1.0 - (days_to_fomc / 14.0)) * 0.5

    # ── Monthly Macro Releases ─────────────────────────────────────────────
    in_macro_week = any(
        m == month and s <= day <= e
        for m, s, e in ECON_RELEASE_WINDOWS
    )
    # First 2 weeks of month: elevated volatility around data releases
    in_cpi_week = 8 <= day <= 14
    # Jobs Friday: typically first Friday (or second if New Year falls on 1st)
    is_employment_friday = (
        weekday == 4 and 1 <= day <= 14 and month not in [1]
    )

    # ── Pension Rebalancing ───────────────────────────────────────────────
    # Last 3 trading days of month (pension funds rebalance end of quarter)
    in_pension_rebalance = day >= 25 and weekday < 5

    # ── Quarter-End ────────────────────────────────────────────────────────
    is_quarter_end = month in [3, 6, 9, 12] and day >= 25
    is_quarter_start = month in [1, 4, 7, 10] and day <= 10

    # ── Year-End ───────────────────────────────────────────────────────────
    is_year_end = month == 12 and day >= 20
    is_january = month == 1

    # ── Composite Calendar Score ────────────────────────────────────────────
    # Multiplier applied to signal conviction during high-volatility windows
    calendar_pressure = 0.0
    if in_earnings_season: calendar_pressure += 0.25
    if in_fomc_week: calendar_pressure += 0.30
    if in_macro_week: calendar_pressure += 0.15
    if in_pension_rebalance: calendar_pressure += 0.10
    if is_year_end: calendar_pressure += 0.15
    if is_quarter_end: calendar_pressure += 0.05

    return {
        "in_earnings_season": in_earnings_season,
        "earnings_season_score": earnings_season_score,
        "days_into_earnings": days_into_earnings,
        "in_fomc_week": in_fomc_week,
        "fomc_risk": fomc_risk,
        "days_to_fomc": days_to_fomc,
        "in_macro_week": in_macro_week,
        "in_cpi_week": in_cpi_week,
        "is_employment_friday": is_employment_friday,
        "in_pension_rebalance": in_pension_rebalance,
        "is_quarter_end": is_quarter_end,
        "is_quarter_start": is_quarter_start,
        "is_year_end": is_year_end,
        "is_january": is_january,
        "calendar_pressure": min(1.0, calendar_pressure),
        "month": month,
        "day": day,
        "week_of_month": week_of_month,
    }


CAL_CONTEXT = get_calendar_context()


# ── Fed Rate Monitor (Portfolio Manager) ──────────────────────────────────────
# Same logic as market_scan.py — live 10Y yield, regime classification, FOMC countdown
def get_fed_regime_manager():
    import yfinance as yf
    rate_data = {
        "ten_year": None, "two_year": None, "spread_10y2y": None,
        "regime": "NEUTRAL", "rate_direction": "STABLE",
        "fomc_countdown": None, "next_fomc_date": "unknown",
        "fed_watch": "🟡 neutral", "last_updated": None,
    }
    try:
        fi_10 = yf.Ticker("^TNX").fast_info
        fi_2 = yf.Ticker("^FVX").fast_info
        ten_yr = getattr(fi_10, "last_price", None)
        two_yr = getattr(fi_2, "last_price", None)
        if ten_yr:
            rate_data["ten_year"] = round(float(ten_yr), 3)
        if two_yr:
            rate_data["two_year"] = round(float(two_yr), 3)
        if ten_yr and two_yr:
            rate_data["spread_10y2y"] = round(float(ten_yr) - float(two_yr), 3)
            if ten_yr > 5.0:
                rate_data["regime"] = "VERY_TIGHT"
                rate_data["fed_watch"] = "🔴 VERY TIGHT"
            elif ten_yr > 4.5:
                rate_data["regime"] = "RESTRICTIVE"
                rate_data["fed_watch"] = "🟠 RESTRICTIVE"
            elif ten_yr > 3.5:
                rate_data["regime"] = "NEUTRAL"
                rate_data["fed_watch"] = "🟡 NEUTRAL"
            else:
                rate_data["regime"] = "ACCOMMODATIVE"
                rate_data["fed_watch"] = "🟢 ACCOMMODATIVE"
            try:
                t = yf.Ticker("^TNX")
                hist = t.history(period="1mo", interval="1d")
                if hist is not None and len(hist) >= 5:
                    ma30 = hist["Close"].mean()
                    if ten_yr > ma30 * 1.01:
                        rate_data["rate_direction"] = "RISING"
                    elif ten_yr < ma30 * 0.99:
                        rate_data["rate_direction"] = "FALLING"
                    else:
                        rate_data["rate_direction"] = "STABLE"
            except Exception:
                pass
        rate_data["last_updated"] = datetime.now().strftime("%H:%M ET")
    except Exception:
        rate_data["fed_watch"] = "⚠️ rate data unavailable"

    now = datetime.now()
    year = now.year
    next_fomc = None
    for m, d_start, d_end in FOMC_WINDOWS:
        if m >= now.month:
            fomc_date = datetime(year, m, d_start)
            if fomc_date >= now:
                next_fomc = fomc_date
                break
    if next_fomc:
        delta = next_fomc - now
        rate_data["fomc_countdown"] = delta.days
        rate_data["next_fomc_date"] = next_fomc.strftime("%b %d")
    return rate_data

FED_REGIME_MGR = get_fed_regime_manager()


# ─────────────────────────────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────────────────────────────
class ScoreEngine:
    """Quick triage scoring — 6 rules, 30+ metrics. Works for stocks AND ETFs."""

    def __init__(self):
        self._cache = {}

    def _ticker(self, symbol):
        if symbol in self._cache:
            return self._cache[symbol]
        try:
            import yfinance as yf
            t = yf.Ticker(symbol)
            info = t.info or {}

            # ETF-specific: use fast_info for reliable price data
            try:
                fi = t.fast_info
                info["currentPrice"] = getattr(fi, "market_cap", None) or info.get("currentPrice")
                # For ETFs, lastPrice is more reliable
                if not info.get("currentPrice") and hasattr(fi, "last_price"):
                    info["currentPrice"] = fi.last_price
            except:
                pass

            # Get history carefully (may fail for some tickers)
            try:
                hist = t.history(period="3mo", interval="1d")
            except:
                hist = None

            try:
                financials = t.financials
                balance = t.balance_sheet
                cashflow = t.cashflow
            except:
                financials = balance = cashflow = None

            self._cache[symbol] = {"info": info, "hist": hist,
                                   "fin": financials, "bal": balance, "cf": cashflow}
            return self._cache[symbol]
        except Exception as e:
            return {"info": {}, "hist": None, "fin": None, "bal": None, "cf": None, "error": str(e)}

    def _f(self, val, default=0.0):
        if val is None or (isinstance(val, float) and val != val):
            return default
        try:
            return float(val)
        except:
            return default

    def _price(self, info):
        """
        Get current price from info dict. Tries multiple keys for stocks AND ETFs.
        BUG FIX: yfinance sometimes returns market cap as 'currentPrice' for stocks.
        We detect this by checking bounds (price should be < $50,000 for any US stock).
        """
        candidates = {}
        for key in ["currentPrice", "regularMarketPrice", "navPrice",
                    "lastPrice", "previousClose"]:
            v = info.get(key)
            if v is not None and isinstance(v, (int, float)) and v > 0:
                # Sanity check: prices for any US stock/ETF should be < $50,000
                # Market caps can be trillions — filter those out
                if v < 50000:
                    candidates[key] = float(v)

        # Prefer: regularMarketPrice (ETF-friendly) > currentPrice (stock-friendly)
        for key in ["regularMarketPrice", "currentPrice", "navPrice",
                    "lastPrice", "previousClose"]:
            if key in candidates:
                return candidates[key]

        return None

    def _hist_last(self, hist, col="Close", days=1):
        if hist is None or hist.empty or len(hist) < days:
            return None
        try:
            return float(hist[col].iloc[-days])
        except:
            return None

    # ── Rule 1: Fundamental ──────────────────────────────────────────────────
    def rule1(self, d, is_etf=False):
        """Quality, earnings, balance sheet. Max 100."""
        info = d["info"]
        scores = {}

        if is_etf:
            # ETF Rule 1: expense ratio, yield, AUM, age, tracking
            exp_ratio = self._f(info.get("expenseRatio", info.get("annualReportExpenseRatio")))
            yield_ = self._f(info.get("dividendYield", info.get("fundYield")))
            aum = self._f(info.get("totalAssets") or info.get("navPrice"))
            # Expense ratio: 0 = 100, 1%+ = 0
            scores["f1"] = max(0, min(100, (0.5 - exp_ratio) * 200)) if exp_ratio else 40
            # Yield: higher = better for income ETFs
            scores["f2"] = min(100, yield_ * 400) if yield_ else 40
            # AUM: >$1B = institutional quality
            scores["f3"] = min(100, 50 + (aum / 1e9) * 5) if aum else 40
            # Performance vs benchmark (use 1yr return)
            ret_1y = self._f(info.get("annualPerformance") or info.get("threeYearPerformance"))
            scores["f4"] = min(100, max(0, 50 + ret_1y)) if ret_1y else 50
            # Age / track record
            scores["f5"] = 70  # default for established ETFs
            f1_total = sum(scores[k] * {"f1": 0.30, "f2": 0.20, "f3": 0.20, "f4": 0.20, "f5": 0.10}[k] for k in scores)
        else:
            # Stock Rule 1: earnings yield, growth, margins, ROE, balance sheet
            pe = self._f(info.get("trailingPE"))
            earnings_yield = (100/pe) if pe and pe > 0 else 0
            scores["f1"] = min(100, earnings_yield * 5)

            eps_fwd = self._f(info.get("forwardEps"))
            eps_ttm = self._f(info.get("trailingEps"))
            if eps_ttm and eps_fwd and eps_ttm > 0:
                growth = ((eps_fwd - eps_ttm) / eps_ttm) * 100
                scores["f2"] = min(100, max(0, growth * 10))
            else:
                scores["f2"] = 25

            gross = self._f(info.get("grossProfitMargin", info.get("grossMargin")))
            op_mar = self._f(info.get("operatingMargin"))
            net_mar = self._f(info.get("profitMargin"))
            vals = [v for v in [gross, op_mar, net_mar] if v is not None and v > 0]
            avg_mar = sum(vals)/len(vals) if vals else (net_mar or 0)
            scores["f3"] = min(100, avg_mar * 100)

            roe = self._f(info.get("returnOnEquity"))
            scores["f4"] = min(100, roe * 100) if roe else 30

            de = self._f(info.get("debtToEquity"))
            scores["f5"] = max(0, min(100, (5 - de) * 20)) if de is not None and de >= 0 else 50

            weights = {"f1": 0.20, "f2": 0.25, "f3": 0.20, "f4": 0.20, "f5": 0.15}
            f1_total = sum(scores[k] * weights[k] for k in weights)

        return f1_total, scores

    # ── Rule 2: Opportunistic ───────────────────────────────────────────────
    def rule2(self, d):
        info = d["info"]
        scores = {}
        cp = self._price(info) or 0
        high52 = self._f(info.get("fiftyTwoWeekHigh"))
        low52 = self._f(info.get("fiftyTwoWeekLow"))
        avg200 = self._f(info.get("twoHundredDayAverage"))
        avg50 = self._f(info.get("fiftyDayAverage"))

        pullback = ((high52 - cp) / high52 * 100) if high52 and high52 > 0 and cp > 0 else 0
        scores["o1"] = min(100, pullback * 5)

        if avg200 and avg200 > 0 and cp > 0:
            scores["o2"] = 50 + (cp - avg200) / avg200 * 100 if cp >= avg200 else max(0, 50 - (avg200 - cp) / avg200 * 100)
        else:
            scores["o2"] = 40

        rec = (info.get("recommendationKey") or "neutral").lower()
        rec_map = {"strongbuy": 25, "buy": 38, "hold": 50, "sell": 62, "strongsell": 78}
        rsi_proxy = rec_map.get(rec, 50)
        if rsi_proxy < 40:
            scores["o3"] = min(100, (40 - rsi_proxy) * 2.5 + 50)
        elif rsi_proxy > 65:
            scores["o3"] = max(0, 50 - (rsi_proxy - 65) * 2.5)
        else:
            scores["o3"] = 50

        peg = self._f(info.get("pegRatio"))
        scores["o4"] = min(100, max(0, (2 - peg) * 50)) if peg and peg > 0 else 35

        rev_g = self._f(info.get("revenueGrowth"))
        scores["o5"] = min(100, max(0, rev_g * 500)) if rev_g else 40

        weights = {"o1": 0.25, "o2": 0.20, "o3": 0.25, "o4": 0.15, "o5": 0.15}
        return sum(scores[k] * weights[k] for k in weights), scores

    # ── Rule 3: Market Event ─────────────────────────────────────────────────
    def rule3(self, d, is_etf=False):
        info = d["info"]
        scores = {}
        sector = (info.get("sector") or info.get("category") or "").lower()

        favored_sectors = ["technology", "information technology", "communication services",
                          "industrials", "healthcare", "consumer discretionary"]
        neutral_sectors = ["consumer staples", "utilities", "real estate"]
        disfavored_sectors = ["energy", "basic materials", "materials"]

        if sector in favored_sectors:
            scores["m1"] = 80
        elif sector in neutral_sectors:
            scores["m1"] = 55
        elif sector in disfavored_sectors:
            scores["m1"] = 30
        else:
            scores["m1"] = 55

        mcap = self._f(info.get("marketCap") or info.get("totalAssets"))
        if mcap and mcap > 1e12: scores["m2"] = 95
        elif mcap and mcap > 1e11: scores["m2"] = 80
        elif mcap and mcap > 1e10: scores["m2"] = 60
        elif mcap and mcap > 1e9: scores["m2"] = 45
        else: scores["m2"] = 30

        vol = self._f(info.get("averageVolume"))
        vol_today = self._f(info.get("volume"))
        vr = (vol_today / vol) if vol and vol > 0 else 1.0
        scores["m3"] = 85 if vr > 1.5 else (65 if vr > 0.8 else 40)

        eq_g = self._f(info.get("earningsQuarterlyGrowth"))
        scores["m4"] = min(100, max(0, 50 + eq_g * 200)) if eq_g else 50

        scores["m5"] = 85 if is_etf else 65

        weights = {"m1": 0.30, "m2": 0.20, "m3": 0.20, "m4": 0.15, "m5": 0.15}
        return sum(scores[k] * weights[k] for k in weights), scores

    # ── Rule 4: Political Alignment ─────────────────────────────────────────
    def rule4(self, d, is_etf=False):
        info = d["info"]
        scores = {}
        sector = (info.get("sector") or info.get("category") or "").lower()
        industry = (info.get("industry") or "").lower()
        sym = (info.get("symbol") or "").upper()

        ai_syms = ["NVDA", "AMD", "AVGO", "QCOM", "META", "GOOGL", "AMZN", "MSFT"]
        ai_kws = ["semiconductor", "software", "cloud", "technology", "digital", "ai"]
        if sym in ai_syms or any(k in industry for k in ai_kws):
            scores["p1"] = 88
        elif sector == "technology" and any(k in industry for k in ["chip", "semiconductor", "electronics"]):
            scores["p1"] = 92
        elif sector == "healthcare":
            scores["p1"] = 60
        elif sector == "energy":
            scores["p1"] = 35
        else:
            scores["p1"] = 55

        if sym in ["BAC", "JPM", "GS", "C", "MS"]:
            scores["p2"] = 30
        elif sector == "financials":
            scores["p2"] = 45
        else:
            scores["p2"] = 65

        if any(k in industry for k in ["ev", "solar", "wind", "renewable"]):
            scores["p3"] = 75
        elif any(k in industry for k in ["tobacco", "alcohol", "gambling"]):
            scores["p3"] = 25
        else:
            scores["p3"] = 55

        country = (info.get("country") or "US")
        scores["p4"] = 80 if country == "United States" else 40

        geo_kws = ["gold", "defense", "military", "staples", "consumer staples"]
        if sym in ["GLD", "IAU", "GDX", "XLP", "XLF", "ITA"] or any(k in industry for k in geo_kws):
            scores["p5"] = 80
        else:
            scores["p5"] = 50

        weights = {"p1": 0.35, "p2": 0.20, "p3": 0.15, "p4": 0.15, "p5": 0.15}
        return sum(scores[k] * weights[k] for k in weights), scores

    # ── Rule 5: Quantitative ─────────────────────────────────────────────────
    def rule5(self, d, is_etf=False):
        info = d["info"]
        hist = d["hist"]
        scores = {}
        cp = self._price(info) or 0
        high52 = self._f(info.get("fiftyTwoWeekHigh"))
        low52 = self._f(info.get("fiftyTwoWeekLow"))
        avg200 = self._f(info.get("twoHundredDayAverage"))
        avg50 = self._f(info.get("fiftyDayAverage"))

        if avg200 and avg200 > 0 and cp > 0:
            scores["q1"] = 50 + (cp - avg200) / avg200 * 200 if cp >= avg200 else max(0, 50 - (avg200 - cp) / avg200 * 200)
        else:
            scores["q1"] = 50

        if avg50 and avg200 and avg50 > 0 and avg200 > 0:
            scores["q2"] = 50 + (avg50 - avg200) / avg200 * 200 if avg50 >= avg200 else max(0, 50 - (avg200 - avg50) / avg200 * 200)
        else:
            scores["q2"] = 50

        pct_from_high = ((high52 - cp) / high52 * 100) if high52 and high52 > 0 and cp > 0 else 0
        if pct_from_high <= 0: scores["q3"] = 100
        elif pct_from_high < 5: scores["q3"] = 85
        elif pct_from_high < 10: scores["q3"] = 70
        elif pct_from_high < 20: scores["q3"] = 55
        else: scores["q3"] = max(0, 35 - pct_from_high)

        if hist is not None and len(hist) >= 60:
            current = self._hist_last(hist, "Close", 1)
            start_price = self._hist_last(hist, "Close", min(60, len(hist)))
            if current and start_price and start_price > 0:
                rel_str = (current / start_price - 1) * 100
                scores["q4"] = min(100, max(0, 50 + rel_str * 3))
            else:
                scores["q4"] = 50
        else:
            scores["q4"] = 50

        beta = self._f(info.get("beta"))
        if beta and beta > 0:
            scores["q5"] = 85 if beta < 0.8 else (60 if beta < 1.2 else max(0, 50 - (beta - 1.2) * 25))
        else:
            scores["q5"] = 55

        weights = {"q1": 0.25, "q2": 0.25, "q3": 0.25, "q4": 0.15, "q5": 0.10}
        return sum(scores[k] * weights[k] for k in weights), scores

    # ── Rule 6: Calendar + Fed Rate Regime Context ─────────────────────────
    def rule6(self, d, cal_ctx=None, fed_regime=None):
        """
        Temporal + monetary policy scoring — modulates score based on:
        1. Earnings / FOMC / macro calendar (t1–t5)
        2. Fed rate regime — 10Y yield level + direction (t6–t7)

        During high-volatility windows (earnings season, FOMC week, macro week):
        - Volatile stocks get penalized (earnings-exposed stocks in earnings season)
        - Safe-haven / low-beta stocks get a boost
        - Confidence in signals is reduced

        Fed regime logic:
        - VERY_TIGHT (>5.0% 10Y): penalize high-P/E growth, reward value/short duration
        - RESTRICTIVE (4.5–5.0%): banks benefit, long-duration growth hurt
        - NEUTRAL (3.5–4.5%): balanced, no regime bias
        - ACCOMMODATIVE (<3.5%): growth stocks re-rate higher, utilities/REITs boosted
        """
        if cal_ctx is None:
            cal_ctx = CAL_CONTEXT
        if fed_regime is None:
            fed_regime = FED_REGIME_MGR

        info = d["info"]
        scores = {}

        # ── Stock-specific earnings exposure ──────────────────────────────────
        sector = (info.get("sector") or "").lower()
        industry = (info.get("industry") or "").lower()
        beta = self._f(info.get("beta"))
        pe = self._f(info.get("trailingPE"))
        earnings_yield = self._f(info.get("trailingPE"))
        if earnings_yield and earnings_yield > 0:
            ey = 100 / earnings_yield
        else:
            ey = 0

        # High earnings exposure: consumer discretionary, tech, financials
        high_earn_syms = ["NFLX", "AMZN", "GOOGL", "META", "NVDA", "AMD", "INTC",
                          "BAC", "JPM", "GS", "C", "MS", "XLF", "XLK"]
        earn_exposure = 0.0
        sym = info.get("symbol", "")
        if sym in high_earn_syms or any(k in industry for k in ["technology", "semiconductor",
                                                                   "cloud", "bank", "financial"]):
            earn_exposure = 1.0
        elif sector in ["consumer discretionary", "information technology",
                         "financials", "communication services"]:
            earn_exposure = 0.7
        elif sector in ["healthcare", "industrials", "consumer staples"]:
            earn_exposure = 0.4
        else:
            earn_exposure = 0.5

        # ── Earnings Season Scoring ─────────────────────────────────────────
        if cal_ctx["in_earnings_season"]:
            earn_penalty = earn_exposure * cal_ctx["days_into_earnings"] * 0.8
            scores["t1"] = max(0, 70 - earn_penalty)
        else:
            scores["t1"] = 75

        # ── FOMC Risk Scoring ───────────────────────────────────────────────
        if cal_ctx["in_fomc_week"]:
            if beta and beta > 0:
                scores["t2"] = max(20, 75 - (beta - 1.0) * 40)
            else:
                scores["t2"] = 65
        elif cal_ctx["fomc_risk"] > 0:
            scores["t2"] = 70 - cal_ctx["fomc_risk"] * 15
        else:
            scores["t2"] = 75

        # ── Monthly Macro / CPI Week ────────────────────────────────────────
        if cal_ctx["in_cpi_week"] or cal_ctx["is_employment_friday"]:
            macro_sensitive = ["XLU", "VNQ", "XLP", "VYM", "DVY", "GLD", "IAU"]
            if sym in macro_sensitive or sector in ["utilities", "real estate",
                                                      "consumer staples"]:
                scores["t3"] = 80
            elif sector in ["technology", "consumer discretionary"]:
                scores["t3"] = max(40, 65 - cal_ctx["calendar_pressure"] * 20)
            else:
                scores["t3"] = 65
        else:
            scores["t3"] = 70

        # ── Pension Rebalance / Quarter-End ────────────────────────────────
        if cal_ctx["in_pension_rebalance"] or cal_ctx["is_quarter_end"]:
            avg_vol = self._f(info.get("averageVolume"))
            if avg_vol and avg_vol > 5e6:
                scores["t4"] = 80
            elif beta and beta < 0.9:
                scores["t4"] = 75
            else:
                scores["t4"] = 55
        else:
            scores["t4"] = 68

        # ── Year-End / January Effect ───────────────────────────────────────
        if cal_ctx["is_year_end"]:
            mcap = self._f(info.get("marketCap"))
            if mcap and mcap < 5e9:
                scores["t5"] = 80
            elif sector in ["small cap", "mid cap"]:
                scores["t5"] = 78
            else:
                scores["t5"] = 65
        elif cal_ctx["is_january"]:
            scores["t5"] = 75
        else:
            scores["t5"] = 65

        # ── Fed Rate Regime Scoring (t6, t7) ─────────────────────────────
        ten_yr = fed_regime.get("ten_year")
        regime = fed_regime.get("regime", "NEUTRAL")
        rate_dir = fed_regime.get("rate_direction", "STABLE")

        if ten_yr:
            if "VERY_TIGHT" in regime or "RESTRICTIVE" in regime:
                # High P/E growth stocks get penalized
                if pe and pe > 30:
                    scores["t6"] = max(30, 75 - (pe - 30) * 1.5)
                elif pe and pe < 20:
                    scores["t6"] = 80  # value scores well
                else:
                    scores["t6"] = 65

                # Banks get boost from steep yield curve
                if sym in ["BAC", "JPM", "GS", "C", "MS", "KEY", "MTB", "USB", "TFC"]:
                    scores["t6"] = 88

                # REITs / utilities penalized
                rate_sens = ["VNQ", "XLRE", "IYR", "XLU"]
                if sym in rate_sens:
                    scores["t6"] = max(25, scores["t6"] - 25)

            elif "ACCOMMODATIVE" in regime:
                # Low rates: growth re-rates higher
                if pe and pe > 25:
                    scores["t6"] = 80
                elif sym in ["VNQ", "XLRE", "IYR", "XLU"]:
                    scores["t6"] = 85
                else:
                    scores["t6"] = 68
            else:
                scores["t6"] = 70
        else:
            scores["t6"] = 68

        # Rate direction: rising or falling yields
        if rate_dir == "RISING":
            if beta and beta > 1.2:
                scores["t7"] = max(30, 70 - (beta - 1.0) * 30)
            else:
                scores["t7"] = 68
        elif rate_dir == "FALLING":
            if pe and pe > 20:
                scores["t7"] = 78  # falling yields = growth re-rates
            else:
                scores["t7"] = 65
        else:
            scores["t7"] = 65

        weights = {"t1": 0.18, "t2": 0.18, "t3": 0.15, "t4": 0.10,
                   "t5": 0.12, "t6": 0.17, "t7": 0.10}
        return sum(scores[k] * weights[k] for k in weights), scores

    def composite(self, r1, r2, r3, r4, r5, r6, cal_ctx=None, fed_regime=None):
        if cal_ctx is None:
            cal_ctx = CAL_CONTEXT
        if fed_regime is None:
            fed_regime = FED_REGIME_MGR

        # Base composite
        base = r1 * 0.22 + r2 * 0.18 + r3 * 0.15 + r4 * 0.10 + r5 * 0.35

        # Calendar pressure modulates score — compress toward 50 during high-volatility windows
        pressure = cal_ctx["calendar_pressure"]
        midpoint = 50
        if pressure > 0:
            compression = min(0.15, pressure * 0.20)
            base = midpoint + (base - midpoint) * (1.0 - compression)

        # Fed regime: additional modulation on top of calendar pressure
        # In VERY_TIGHT or RESTRICTIVE regime, penalize high-P/E further
        regime = fed_regime.get("regime", "NEUTRAL")
        if "VERY_TIGHT" in regime:
            # Very restrictive — additional score compression for growth
            base = midpoint + (base - midpoint) * 0.92
        elif "RESTRICTIVE" in regime:
            base = midpoint + (base - midpoint) * 0.96

        return base

    def score(self, symbol):
        d = self._ticker(symbol)
        if "error" in d:
            return {"symbol": symbol, "error": d["error"]}

        is_etf = symbol in ["SPY","QQQ","IWM","DIA","VTI","XLK","XLF","XLV","XLE",
                           "XLI","XLB","XLY","XLP","XLRE","XLU","XLC","SOXX",
                           "SMH","GLD","IAU","VNQ","VYM","DVY","QQQ","SPXL",
                           "TQQQ","SDS","SSO","QID"] or "etf" in (d["info"].get("quoteType") or "").lower()

        r1, r1d = self.rule1(d, is_etf)
        r2, r2d = self.rule2(d)
        r3, r3d = self.rule3(d, is_etf)
        r4, r4d = self.rule4(d, is_etf)
        r5, r5d = self.rule5(d, is_etf)
        r6, r6d = self.rule6(d, CAL_CONTEXT, FED_REGIME_MGR)
        cs = self.composite(r1, r2, r3, r4, r5, r6, CAL_CONTEXT, FED_REGIME_MGR)

        cp = self._price(d["info"])
        high52 = self._f(d["info"].get("fiftyTwoWeekHigh"))

        # Dynamic thresholds: tighten on high-pressure calendar windows
        # BUY: 65 normally → up to 75 in high-pressure weeks
        # SELL: 40 normally → down to 35 in high-pressure weeks
        pressure = CAL_CONTEXT["calendar_pressure"]
        buy_thresh = 65 + pressure * 10   # 65–75
        sell_thresh = max(35, 40 - pressure * 5)

        if cs >= buy_thresh: status = "buy"
        elif cs >= 45: status = "hold"
        else: status = "avoid"

        return {
            "symbol": symbol,
            "score_date": TODAY,
            "tier": "quick",
            "f_earning_quality": r1d.get("f1"),
            "f_growth_rate": r1d.get("f2"),
            "f_balance_sheet": r1d.get("f3"),
            "f_market_position": r1d.get("f4"),
            "f_profitability": r1d.get("f5"),
            "f_rule1总分": round(r1, 1),
            "o_pullback_depth": r2d.get("o1"),
            "o_mean_reversion": r2d.get("o2"),
            "o_sector_recovery": r2d.get("o3"),
            "o_sentiment_turn": r2d.get("o4"),
            "o_value_distance": r2d.get("o5"),
            "o_rule2总分": round(r2, 1),
            "m_sector_rotation": r3d.get("m1"),
            "m_macro_tailwind": r3d.get("m2"),
            "m_policy_benefit": r3d.get("m3"),
            "m_feed_flows": r3d.get("m4"),
            "m_market_cap": r3d.get("m5"),
            "m_rule3总分": round(r3, 1),
            "p_policy_exposure": r4d.get("p1"),
            "p_regulatory_risk": r4d.get("p2"),
            "p_subsidy_benefit": r4d.get("p3"),
            "p_trade_exposure": r4d.get("p4"),
            "p_geopolitical": r4d.get("p5"),
            "p_rule4总分": round(r4, 1),
            "q_trend_score": r5d.get("q1"),
            "q_momentum": r5d.get("q2"),
            "q_low_volatility": r5d.get("q3"),
            "q_relative_strength": r5d.get("q4"),
            "q_vol_profile": r5d.get("q5"),
            "q_rule5总分": round(r5, 1),
            "rule1": round(r1, 1),
            "rule2": round(r2, 1),
            "rule3": round(r3, 1),
            "rule4": round(r4, 1),
            "rule5": round(r5, 1),
            "rule6": round(r6, 1),
            "t_earnings_season": r6d.get("t1"),
            "t_fomc_risk": r6d.get("t2"),
            "t_macro_week": r6d.get("t3"),
            "t_pension_rebalance": r6d.get("t4"),
            "t_year_end": r6d.get("t5"),
            "t_fed_regime": r6d.get("t6"),
            "t_rate_direction": r6d.get("t7"),
            "composite_score": round(cs, 1),
            "scan_status": status,
            "current_price": cp,
            "fifty_two_high": high52,
            "calendar_pressure": CAL_CONTEXT["calendar_pressure"],
            "in_earnings_season": CAL_CONTEXT["in_earnings_season"],
            "in_fomc_week": CAL_CONTEXT["in_fomc_week"],
            "in_macro_week": CAL_CONTEXT["in_macro_week"],
            "in_pension_rebalance": CAL_CONTEXT["in_pension_rebalance"],
            "buy_threshold": round(buy_thresh, 1),
            "sell_threshold": round(sell_thresh, 1),
            # Fed regime fields
            "fed_ten_year": FED_REGIME_MGR.get("ten_year"),
            "fed_regime": FED_REGIME_MGR.get("regime"),
            "fed_rate_direction": FED_REGIME_MGR.get("rate_direction"),
            "fed_fomc_countdown": FED_REGIME_MGR.get("fomc_countdown"),
            "fed_spread_10y2y": FED_REGIME_MGR.get("spread_10y2y"),
        }

    def save(self, result):
        conn = get_db()
        cols = list(result.keys())
        placeholders = ", ".join([f":{c}" for c in cols])
        sql = f"INSERT OR REPLACE INTO scores ({', '.join(cols)}) VALUES ({placeholders})"
        conn.execute(sql, result)
        conn.commit()
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# ALPACA HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def alpaca_get(url):
    r = requests.get(f"{ALPACA_BASE}{url}", headers=HEADERS, timeout=10)
    return r.json() if r.status_code == 200 else None

def alpaca_post(url, payload):
    r = requests.post(f"{ALPACA_BASE}{url}", headers=HEADERS, json=payload, timeout=10)
    return r.json() if r.status_code in (200, 201) else None

def get_account():
    return alpaca_get("/v2/account")

def get_positions():
    return alpaca_get("/v2/positions") or []

def get_orders(status="all", limit=50):
    return alpaca_get(f"/v2/orders?status={status}&limit={limit}") or []

def get_clock():
    return alpaca_get("/v2/clock") or {}

def is_market_open():
    return get_clock().get("is_open", False)

# ─────────────────────────────────────────────────────────────────────────────
# PORTFOLIO CROSS-MATCHER
# ─────────────────────────────────────────────────────────────────────────────
def sync_portfolio():
    """Sync Alpaca positions into our portfolio table."""
    positions = get_positions()
    conn = get_db()
    conn.execute("DELETE FROM portfolio")
    for p in positions:
        conn.execute("""
            INSERT OR REPLACE INTO portfolio
            (symbol, shares, avg_cost, current_price, market_value,
             unrealized_pl, unrealized_plpct, sector, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p["symbol"], float(p["qty"]), float(p["avg_entry_price"]),
             float(p["current_price"]), float(p["market_value"]),
             float(p["unrealized_pl"]), float(p["unrealized_plpc"]) * 100,
             "Unknown", datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return positions

def check_signals():
    """
    Check portfolio holdings vs library for new opportunities.
    Logic:
    - Portfolio holding's score dropped below 40 → signal SELL
    - Library stock score >= 70 + sector match → signal BUY
    - Portfolio holding replaced by better-scoring ETF → flag as SWAP
    """
    conn = get_db()

    # Get portfolio positions
    portfolio_syms = [r["symbol"] for r in conn.execute("SELECT symbol FROM portfolio").fetchall()]

    # Get library stocks with recent scores (score_date = TODAY or yesterday)
    yesterday = (datetime.now() - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")
    library_candidates = conn.execute("""
        SELECT symbol, composite_score, scan_status, rule5总分 as trend_score
        FROM scores
        WHERE score_date IN (?, ?) AND scan_status = 'buy' AND symbol NOT IN (
            SELECT symbol FROM portfolio)
        ORDER BY composite_score DESC LIMIT 20""", (TODAY, yesterday)).fetchall()

    signals_created = []

    # Check if any portfolio positions need attention
    for sym in portfolio_syms:
        score_row = conn.execute("""
            SELECT composite_score, scan_status FROM scores
            WHERE symbol = ? AND score_date IN (?, ?)
            ORDER BY score_date DESC LIMIT 1""", (sym, TODAY, yesterday)).fetchone()
        if score_row and score_row["composite_score"] < 40:
            # Generate SELL signal
            conn.execute("""
                INSERT INTO signals (symbol, signal_date, signal_type, trigger_rule,
                trigger_detail, score_before, price_at_signal, conviction, status)
                VALUES (?, ?, 'sell', 'rule_composite',
                'Portfolio holding composite score below 40', ?, ?, 'high', 'active')""",
                (sym, TODAY, score_row["composite_score"],
                 alpaca_get(f"/v2/positions/{sym}") or {}))
            signals_created.append(f"SELL {sym} (score={score_row['composite_score']:.1f})")

    conn.commit()
    conn.close()
    return signals_created


# ─────────────────────────────────────────────────────────────────────────────
# LIBRARY BUILDER — 10 stocks/day
# ─────────────────────────────────────────────────────────────────────────────
DAILY_BUILD_COUNT = 10

def build_library():
    """
    Score the next DAILY_BUILD_COUNT pending stocks from the library queue.
    Run once per day (cron at 9 AM ET).
    """
    engine = ScoreEngine()
    conn = get_db()

    # Get next 10 pending stocks ordered by priority
    rows = conn.execute("""
        SELECT symbol, tier FROM library_queue
        WHERE status = 'pending'
        ORDER BY priority DESC, created_at ASC
        LIMIT ?""", (DAILY_BUILD_COUNT,)).fetchall()

    conn.close()

    if not rows:
        print(f"[{TIMESTAMP}] Library queue empty — all stocks scanned")
        return []

    scored = []
    errors = []

    for row in rows:
        sym = row["symbol"]
        tier = row["tier"]
        print(f"  Scoring {sym}...", end=" ", flush=True)
        try:
            result = engine.score(sym)
            if "error" not in result:
                engine.save(result)
                conn2 = get_db()
                conn2.execute(
                    "UPDATE library_queue SET status='scored', scanned_date=?, attempts=attempts+1 WHERE symbol=?",
                    (TODAY, sym))
                conn2.commit()
                conn2.close()
                scored.append(f"{sym}({result['composite_score']:.1f})")
                print(f"✓ composite={result['composite_score']:.1f}")
            else:
                errors.append(f"{sym}: {result['error']}")
                conn2 = get_db()
                conn2.execute(
                    "UPDATE library_queue SET attempts=attempts+1 WHERE symbol=?",
                    (sym,))
                conn2.commit()
                conn2.close()
                print(f"✗ {result['error']}")
        except Exception as e:
            errors.append(f"{sym}: {e}")
            print(f"✗ {e}")
        time.sleep(1.5)  # be polite to Yahoo

    return scored, errors


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
def generate_signals():
    """
    Look at today's scores and generate actionable signals.
    BUY: score >= 65 and not in portfolio
    UPGRADE: score improved >10pts vs last score
    SELL: score dropped below 40 in portfolio
    """
    conn = get_db()
    yesterday = (datetime.now() - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")

    # Top BUY signals from library
    buys = conn.execute("""
        SELECT symbol, composite_score, rule1, rule5, current_price, fifty_two_high, scan_status
        FROM scores
        WHERE score_date = ? AND scan_status = 'buy'
        ORDER BY composite_score DESC LIMIT 15""", (TODAY,)).fetchall()

    signals = []
    for b in buys:
        # Check if already in portfolio
        in_port = conn.execute("SELECT 1 FROM portfolio WHERE symbol = ?", (b["symbol"],)).fetchone()
        if not in_port:
            # Not in portfolio — create BUY signal
            conn.execute("""
                INSERT INTO signals (symbol, signal_date, signal_type, trigger_rule,
                trigger_detail, score_after, price_at_signal, conviction, status)
                VALUES (?, ?, 'buy', 'rule_composite',
                'Score >= 65, BUY signal', ?, ?, 'medium', 'active')""",
                (b["symbol"], TODAY, b["composite_score"], b["current_price"]))
            signals.append(f"BUY {b['symbol']} @ ${b['current_price']:.2f} (score={b['composite_score']:.1f})")

    conn.commit()
    conn.close()
    return signals


# ─────────────────────────────────────────────────────────────────────────────
# ALPACA TRADE PLACER
# ─────────────────────────────────────────────────────────────────────────────
def place_order(symbol, side, qty, order_type="market", limit_price=None):
    """Place an Alpaca order."""
    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": "day",
    }
    if limit_price:
        payload["limit_price"] = str(limit_price)

    result = alpaca_post("/v2/orders", payload)
    if result and "id" in result:
        return result
    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — DAILY RUN
# ─────────────────────────────────────────────────────────────────────────────
def run_daily():
    """
    Daily run (9 AM ET):
    1. Build library: score next 10 stocks
    2. Sync portfolio positions from Alpaca
    3. Generate signals
    4. Log to scan_history
    """
    start = time.time()
    clock = get_clock()
    is_open = clock.get("is_open", False)
    print(f"[{TIMESTAMP}] Daily portfolio run starting...")
    print(f"  Market open: {is_open}")

    # Step 1: Build library
    print(f"\n── Library Build: 10 stocks ──")
    scored, errors = build_library()
    print(f"  Scored: {len(scored)} | Errors: {len(errors)}")

    # Step 2: Sync portfolio
    print(f"\n── Portfolio Sync ──")
    positions = sync_portfolio()
    print(f"  {len(positions)} positions synced")

    # Step 3: Generate signals
    print(f"\n── Signal Generation ──")
    signals = generate_signals()
    print(f"  {len(signals)} new signals")

    duration = time.time() - start
    print(f"\n[{TIMESTAMP}] Daily run complete in {duration:.1f}s")
    print(f"  Scored: {len(scored)} | Signals: {len(signals)} | Positions: {len(positions)}")
    if signals:
        print("\n📋 SIGNALS:")
        for s in signals:
            print(f"  {s}")
    if errors:
        print("\n⚠️ ERRORS:")
        for e in errors:
            print(f"  {e}")

    # Log to scan_history
    conn = get_db()
    conn.execute("""
        INSERT INTO scan_history
        (scan_date, scan_type, stocks_scanned, new_signals, orders_placed, duration_secs, status, errors)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (TODAY, "daily_build", len(scored), len(signals), 0, duration,
         "ok" if not errors else "partial", json.dumps(errors) if errors else None))
    conn.commit()
    conn.close()

    return {
        "scored": scored,
        "signals": signals,
        "positions": len(positions),
        "errors": errors,
        "duration": duration,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-daily", action="store_true", help="Run full daily build")
    parser.add_argument("--test", action="store_true", help="Test scoring on sample stocks")
    args = parser.parse_args()

    if args.test:
        engine = ScoreEngine()
        test_syms = ["AAPL", "GOOGL", "V", "QQQ", "SOXX", "INTC", "NVDA", "SPY"]
        for sym in test_syms:
            r = engine.score(sym)
            if "error" not in r:
                cp = r.get("current_price") or 0
                print(f"{sym:6} ${cp:8.2f} | "
                      f"R1={r['rule1']:5.1f} R2={r['rule2']:5.1f} R3={r['rule3']:5.1f} "
                      f"R4={r['rule4']:5.1f} R5={r['rule5']:5.1f} | "
                      f"CS={r['composite_score']:5.1f} [{r['scan_status']}]")
            else:
                print(f"{sym}: ERROR — {r['error']}")
    elif args.run_daily:
        run_daily()
    else:
        parser.print_help()
        print("\nQuick start:")
        print("  python3 portfolio_manager.py --test")
        print("  python3 portfolio_manager.py --run-daily")