#!/usr/local/bin/python3
"""
Quick Triage Scoring Engine — 29 metrics across 7 strategic rules
Each stock gets scored 0-100 per rule, then composite.

Rule 1 (Fundamental): Quality, earnings power, balance sheet
Rule 2 (Opportunistic): Pullback depth, mean reversion, sector recovery
Rule 3 (Market Event): Sector rotation, macro catalysts, policy
Rule 4 (Political Alignment): Policy beneficiaries/risk, geopolitics
Rule 5 (Quantitative): Trend, momentum, low vol, relative strength
Rule 6 (Calendar/Temporal): Earnings season, FOMC week, CPI/jobs week, pension/quarter-end
Rule 7 (Interest Rate Regime): 10Y yield level + direction, rate-sensitive sectors

Usage:
  from scoring_engine import ScoreEngine
  engine = ScoreEngine()
  result = engine.score("AAPL")
"""

import sys, os, time, json, sqlite3, requests
from datetime import datetime

# yfinance path (we install to /tmp/mkt_pkg)
sys.path.insert(0, "/tmp/mkt_pkg")

try:
    import yfinance as yf
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False

DB_PATH = os.path.expanduser("~/.hermes/cron/output/wealth/portfolio.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─────────────────────────────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class ScoreEngine:
    """Quick triage scoring — 5 rules, 25 metrics, 0-100 per rule."""

    def __init__(self, max_retries=2):
        self.max_retries = max_retries
        self._cache = {}  # symbol -> {info, history, financials}

    def _get_ticker(self, symbol):
        if symbol in self._cache:
            return self._cache[symbol]
        try:
            t = yf.Ticker(symbol)
            info = t.info or {}
            hist = t.history(period="3mo", interval="1d")
            # Try to get financials but don't fail
            try:
                financials = t.financials
                balance = t.balance_sheet
                cashflow = t.cashflow
            except:
                financials = balance = cashflow = None
            self._cache[symbol] = {"info": info, "hist": hist, "fin": financials, "bal": balance, "cf": cashflow}
            return self._cache[symbol]
        except Exception as e:
            return {"info": {}, "hist": None, "fin": None, "bal": None, "cf": None, "error": str(e)}

    def _safe(self, val, default=0.0):
        """Convert to float, handle None/NaN."""
        if val is None or val != val:  # NaN check
            return default
        try:
            return float(val)
        except:
            return default

    def _percentile(self, val, low_anchor, mid_point, high_anchor):
        """Score based on where value falls between anchors."""
        if val >= high_anchor:
            return 100.0
        elif val <= low_anchor:
            return 0.0
        elif val >= mid_point:
            return 50 + 50 * (val - mid_point) / (high_anchor - mid_point)
        else:
            return 50 * (val - low_anchor) / (mid_point - low_anchor)

    # ── Rule 1: Fundamental ─────────────────────────────────────────────────
    def rule1(self, d):
        """Quality, earnings, balance sheet. Max 100."""
        info = d["info"]
        fin = d["fin"]
        bal = d["bal"]
        scores = {}
        total = 0

        # F1: Earnings yield (inverse P/E, normalized)
        pe = self._safe(info.get("trailingPE"))
        earnings_yield = (1/pe * 100) if pe and pe > 0 else 0
        scores["f1"] = min(100, earnings_yield * 5)  # 20% yield = 100

        # F2: EPS growth (5yr expected vs 1yr actual)
        eps_fwd = self._safe(info.get("forwardEps"))
        eps_ttm = self._safe(info.get("trailingEps"))
        if eps_ttm and eps_fwd and eps_ttm > 0:
            growth = ((eps_fwd - eps_ttm) / eps_ttm) * 100
            scores["f2"] = min(100, max(0, growth * 10))
        else:
            scores["f2"] = 25  # neutral if no data

        # F3: Profit margins (gross + operating + net)
        gross = self._safe(info.get("grossProfitMargin", info.get("grossMargin")))
        op_mar = self._safe(info.get("operatingMargin"))
        net_mar = self._safe(info.get("profitMargin"))
        avg_mar = (gross + op_mar + net_mar) / 3 if all(x is not None for x in [gross, op_mar, net_mar]) else net_mar or 0
        scores["f3"] = min(100, avg_mar * 100)

        # F4: Return on Equity (ROE)
        roe = self._safe(info.get("returnOnEquity"))
        scores["f4"] = min(100, roe * 100) if roe else 30

        # F5: Debt-to-Equity (lower is better, inverse scoring)
        de = self._safe(info.get("debtToEquity"))
        if de is not None and de >= 0:
            scores["f5"] = max(0, min(100, (5 - de) * 20))  # 0 debt = 100, 5+ debt = 0
        else:
            scores["f5"] = 50

        # F_Rule1总分 = weighted average
        weights = {"f1": 0.20, "f2": 0.25, "f3": 0.20, "f4": 0.20, "f5": 0.15}
        rule1_total = sum(scores[k] * weights[k] for k in weights)
        return rule1_total, scores

    # ── Rule 2: Opportunistic ────────────────────────────────────────────────
    def rule2(self, d):
        """Oversold, mean reversion, sector recovery. Max 100."""
        info = d["info"]
        hist = d["hist"]
        scores = {}

        cp = self._safe(info.get("currentPrice"))
        high52 = self._safe(info.get("fiftyTwoWeekHigh"))
        low52 = self._safe(info.get("fiftyTwoWeekLow"))
        avg50 = self._safe(info.get("fiftyDayAverage"))
        avg200 = self._safe(info.get("twoHundredDayAverage"))

        # O1: Pullback from 52w high (deeper pullback = higher opportunistic score)
        if high52 and high52 > 0:
            pullback_pct = (high52 - cp) / high52 * 100
            scores["o1"] = min(100, pullback_pct * 5)  # 20% pullback = 100
        else:
            scores["o1"] = 40

        # O2: Below 200-day moving average (below = potentially oversold)
        if avg200 and avg200 > 0:
            if cp < avg200:
                scores["o2"] = min(100, (avg200 - cp) / avg200 * 200)
            else:
                scores["o2"] = max(0, 50 - (cp - avg200) / avg200 * 100)
        else:
            scores["o2"] = 40

        # O3: RSI-14 (oversold = high score, overbought = low)
        rsi14 = self._safe(info.get("fiftyDayRelativeStrengthIndex", info.get("recommendationKey")))
        # Map recommendation to proxy RSI
        rec_map = {"strongBuy": 25, "buy": 35, "hold": 50, "sell": 65, "strongSell": 80}
        if isinstance(rsi14, str):
            rsi14 = rec_map.get(rsi14.lower(), 50)
        if rsi14:
            if rsi14 < 40:
                scores["o3"] = min(100, (40 - rsi14) * 2.5 + 50)
            elif rsi14 > 70:
                scores["o3"] = max(0, 50 - (rsi14 - 70) * 2)
            else:
                scores["o3"] = 50
        else:
            scores["o3"] = 45

        # O4: PEG Ratio (below 1 = cheap growth)
        peg = self._safe(info.get("pegRatio"))
        if peg and peg > 0:
            scores["o4"] = min(100, max(0, (2 - peg) * 50))  # PEG 0 = 100, PEG 2 = 0
        else:
            scores["o4"] = 30

        # O5: Revenue growth acceleration (if 1yr growth > 5yr avg = accelerating)
        rev_1y = self._safe(info.get("revenueGrowth", info.get("revenuePercentChange")))
        rev_5y_approx = self._safe(info.get("revenueGrowth5Y"))
        if rev_1y and rev_5y_approx:
            if rev_1y > rev_5y_approx * 1.2:
                scores["o5"] = min(100, 70 + (rev_1y - rev_5y_approx) * 5)
            else:
                scores["o5"] = 50
        else:
            scores["o5"] = max(0, min(100, rev_1y * 5)) if rev_1y else 40

        weights = {"o1": 0.25, "o2": 0.20, "o3": 0.25, "o4": 0.15, "o5": 0.15}
        rule2_total = sum(scores[k] * weights[k] for k in weights)
        return rule2_total, scores

    # ── Rule 3: Market Event ─────────────────────────────────────────────────
    def rule3(self, d):
        """Sector rotation, macro catalysts. Max 100."""
        info = d["info"]
        scores = {}

        sector = (info.get("sector") or "").lower()
        industry = (info.get("industry") or "").lower()

        # M1: Sector rotation score (tech/industrials/digital infrastructure favored)
        favored = ["technology", "information technology", "communication services",
                  "industrials", "healthcare", "consumer discretionary"]
        neutral = ["consumer staples", "utilities", "real estate"]
        disfavored = ["energy", "materials", "basic materials"]

        if sector in [s.lower() for s in favored]:
            scores["m1"] = 80
        elif sector in [s.lower() for s in neutral]:
            scores["m1"] = 55
        else:
            scores["m1"] = 35

        # M2: Market cap (mega/large cap = more institutional support)
        mcap = self._safe(info.get("marketCap"))
        if mcap and mcap > 0:
            if mcap > 1e12:
                scores["m2"] = 95
            elif mcap > 1e11:
                scores["m2"] = 80
            elif mcap > 1e10:
                scores["m2"] = 60
            elif mcap > 1e9:
                scores["m2"] = 45
            else:
                scores["m2"] = 25
        else:
            scores["m2"] = 40

        # M3: Trading volume (high volume = institutional interest)
        vol = self._safe(info.get("averageVolume") or info.get("averageDailyVolume10Day"))
        vol_ratio = self._safe(info.get("volume") or 0) / vol if vol else 0
        if vol_ratio > 1.5:
            scores["m3"] = 90
        elif vol_ratio > 0.8:
            scores["m3"] = 65
        else:
            scores["m3"] = 40

        # M4: Insider activity proxy (earnings surprise as proxy)
        earnings_beat = self._safe(info.get("earningsQuarterlyGrowth", 0))
        if earnings_beat and earnings_beat > 0.1:
            scores["m4"] = min(100, 60 + earnings_beat * 200)
        else:
            scores["m4"] = max(0, 40 + earnings_beat * 200)

        # M5: Asset class/category fit
        # ETFs get a category score based on focus
        asset_type = info.get("quoteType", "equity").lower()
        if asset_type == "etf":
            category = (info.get("fundFamily") or "").lower()
            # Broad market ETFs score high on event access
            scores["m5"] = 85
        else:
            scores["m5"] = 65

        weights = {"m1": 0.30, "m2": 0.20, "m3": 0.20, "m4": 0.15, "m5": 0.15}
        rule3_total = sum(scores[k] * weights[k] for k in weights)
        return rule3_total, scores

    # ── Rule 4: Politically Aligned ──────────────────────────────────────────
    def rule4(self, d):
        """Policy beneficiaries, regulatory risk. Max 100."""
        info = d["info"]
        scores = {}
        sector = (info.get("sector") or "").lower()
        industry = (info.get("industry") or "").lower()
        sym = (info.get("symbol") or "").upper()

        # P1: Policy exposure score
        # AI/Tech beneficiaries
        ai_syms = ["NVDA", "AMD", "AVGO", "QCOM", "META", "GOOGL", "AMZN", "MSFT", "CRM", "NOW"]
        ai_keywords = ["semiconductor", "software", "cloud computing", "artificial intelligence",
                       "technology", "internet", "digital", "ai"]

        if sym in ai_syms or any(k.lower() in industry for k in ai_keywords):
            scores["p1"] = 85
        # CHIPS Act beneficiaries (semiconductors)
        elif sector == "technology" and any(k in industry for k in ["semiconductor", "chip", "electronics"]):
            scores["p1"] = 90
        # Infrastructure/Industrial
        elif any(k in industry for k in ["construction", "infrastructure", "engineering", "building"]):
            scores["p1"] = 75
        # Healthcare (policy sensitive)
        elif sector == "healthcare":
            scores["p1"] = 60
        # Energy (politically complex)
        elif sector == "energy":
            scores["p1"] = 40
        else:
            scores["p1"] = 55

        # P2: Regulatory risk (inverse - high risk = lower score)
        reg_risk_syms = ["BAC", "JPM", "GS", "C", "MS", "WFC"]  # big banks = high reg
        if sym in reg_risk_syms:
            scores["p2"] = 35
        elif sector in ["financials", "banking"]:
            scores["p2"] = 45
        else:
            scores["p2"] = 65

        # P3: Subsidy/excise tax benefit exposure
        subsidized = ["EV", "solar", "wind", "renewable", "battery", "electric vehicle"]
        taxed = ["tobacco", "alcohol", "gambling", "cannabis"]
        if any(k in industry for k in subsidized):
            scores["p3"] = 75
        elif any(k in industry for k in taxed):
            scores["p3"] = 30
        else:
            scores["p3"] = 55

        # P4: Trade exposure (US-domiciled = lower trade risk)
        country = (info.get("country") or "US")
        if country == "United States":
            scores["p4"] = 80
        else:
            scores["p4"] = 40

        # P5: Geopolitical hedge (gold, defense, staples)
        geo_syms = ["GLD", "IAU", "GDX", "XLF", "IYF", "ITA", "IYJ",
                    "PG", "KO", "PEP", "WMT", "TGT", "XLP"]
        geo_keywords = ["gold", "precious", "defense", "military", "aerospace",
                        "staples", "consumer staples"]
        if sym in geo_syms or any(k in industry for k in geo_keywords):
            scores["p5"] = 80
        else:
            scores["p5"] = 50

        weights = {"p1": 0.35, "p2": 0.20, "p3": 0.15, "p4": 0.15, "p5": 0.15}
        rule4_total = sum(scores[k] * weights[k] for k in weights)
        return rule4_total, scores

    # ── Rule 5: Quantitative ─────────────────────────────────────────────────
    def rule5(self, d):
        """Technicals, trend, momentum. Max 100."""
        info = d["info"]
        hist = d["hist"]
        scores = {}

        cp = self._safe(info.get("currentPrice"))
        high52 = self._safe(info.get("fiftyTwoWeekHigh"))
        low52 = self._safe(info.get("fiftyTwoWeekLow"))
        avg20 = self._safe(info.get("fiftyDayAverage"))
        avg50 = self._safe(info.get("fiftyDayAverage"))
        avg200 = self._safe(info.get("twoHundredDayAverage"))

        # Q1: Trend score (price vs 200d MA)
        if avg200 and avg200 > 0:
            if cp > avg200:
                scores["q1"] = min(100, 50 + (cp - avg200) / avg200 * 200)
            else:
                scores["q1"] = max(0, 50 - (avg200 - cp) / avg200 * 200)
        else:
            scores["q1"] = 50

        # Q2: Momentum (20d vs 50d MA)
        if avg20 and avg50 and avg20 > 0 and avg50 > 0:
            if avg20 > avg50:
                scores["q2"] = min(100, 50 + (avg20 - avg50) / avg50 * 200)
            else:
                scores["q2"] = max(0, 50 - (avg50 - avg20) / avg50 * 200)
        else:
            scores["q2"] = 50

        # Q3: Near 52w high (within 5% = strong trend confirmation)
        if high52 and high52 > 0:
            pct_from_high = (high52 - cp) / high52 * 100
            if pct_from_high <= 0:
                scores["q3"] = 100  # at or above 52w high
            elif pct_from_high < 5:
                scores["q3"] = 80
            elif pct_from_high < 10:
                scores["q3"] = 65
            elif pct_from_high < 20:
                scores["q3"] = 50
            else:
                scores["q3"] = max(0, 30 - pct_from_high)
        else:
            scores["q3"] = 50

        # Q4: 12-month relative strength (need hist data)
        if hist is not None and len(hist) >= 252:
            current = hist["Close"].iloc[-1]
            year_ago = hist["Close"].iloc[-252]
            rel_strength = (current / year_ago - 1) * 100
            scores["q4"] = min(100, max(0, 50 + rel_strength))
        else:
            # Use short period if no full year
            if hist is not None and len(hist) >= 60:
                current = hist["Close"].iloc[-1]
                start = hist["Close"].iloc[min(60, len(hist)-1)]
                rel_strength = (current / start - 1) * 100
                scores["q4"] = min(100, max(0, 50 + rel_strength * 4))
            else:
                scores["q4"] = 50

        # Q5: Low volatility profile (beta-based)
        beta = self._safe(info.get("beta"))
        if beta and beta > 0:
            if beta < 0.8:
                scores["q5"] = 85  # defensive, low vol
            elif beta < 1.2:
                scores["q5"] = 60  # market
            else:
                scores["q5"] = max(0, 50 - (beta - 1.2) * 25)  # high vol penalty
        else:
            scores["q5"] = 55

        weights = {"q1": 0.25, "q2": 0.25, "q3": 0.25, "q4": 0.15, "q5": 0.10}
        rule5_total = sum(scores[k] * weights[k] for k in weights)
        return rule5_total, scores

    # ── Rule 6: Calendar / Temporal Context ─────────────────────────────────────
    def rule6(self, d, cal_ctx=None):
        """
        Earnings season, FOMC week, CPI/jobs week, pension rebalance, year-end.
        Modulates score based on current calendar windows and stock earnings sensitivity.
        """
        if cal_ctx is None:
            cal_ctx = self._get_calendar_context()

        info = d["info"]
        scores = {}
        sector = (info.get("sector") or "").lower()
        industry = (info.get("industry") or "").lower()
        sym = (info.get("symbol") or "").upper()
        beta = self._safe(info.get("beta"))
        pe = self._safe(info.get("trailingPE"))

        # Earnings exposure: high for tech/financials, low for staples/healthcare
        high_earn_syms = ["NFLX", "AMZN", "GOOGL", "META", "NVDA", "AMD", "INTC",
                          "BAC", "JPM", "GS", "C", "MS", "XLF", "XLK"]
        earn_exposure = 0.5
        if sym in high_earn_syms or any(k in industry for k in ["technology", "semiconductor", "cloud", "bank", "financial"]):
            earn_exposure = 1.0
        elif sector in ["consumer discretionary", "information technology",
                        "financials", "communication services"]:
            earn_exposure = 0.7
        elif sector in ["healthcare", "industrials", "consumer staples"]:
            earn_exposure = 0.4

        # t1: Earnings season scoring
        if cal_ctx.get("in_earnings_season"):
            days_into = cal_ctx.get("days_into_earnings", 0)
            earn_penalty = earn_exposure * days_into * 0.8
            scores["t1"] = max(0, 70 - earn_penalty)
        else:
            scores["t1"] = 75

        # t2: FOMC week scoring — penalize high beta
        if cal_ctx.get("in_fomc_week"):
            if beta and beta > 0:
                scores["t2"] = max(20, 75 - (beta - 1.0) * 40)
            else:
                scores["t2"] = 65
        elif cal_ctx.get("fomc_risk", 0) > 0:
            scores["t2"] = 70 - cal_ctx["fomc_risk"] * 15
        else:
            scores["t2"] = 75

        # t3: CPI / Jobs week scoring
        if cal_ctx.get("in_cpi_week") or cal_ctx.get("is_employment_friday"):
            macro_sensitive = ["XLU", "VNQ", "XLP", "VYM", "DVY", "GLD", "IAU"]
            if sym in macro_sensitive or sector in ["utilities", "real estate", "consumer staples"]:
                scores["t3"] = 80
            elif sector in ["technology", "consumer discretionary"]:
                pressure = cal_ctx.get("calendar_pressure", 0)
                scores["t3"] = max(40, 65 - pressure * 20)
            else:
                scores["t3"] = 65
        else:
            scores["t3"] = 70

        # t4: Pension rebalance / Quarter-end
        if cal_ctx.get("in_pension_rebalance") or cal_ctx.get("is_quarter_end"):
            avg_vol = self._safe(info.get("averageVolume"))
            if avg_vol and avg_vol > 5e6:
                scores["t4"] = 80
            elif beta and beta < 0.9:
                scores["t4"] = 75
            else:
                scores["t4"] = 55
        else:
            scores["t4"] = 68

        # t5: Year-end / January effect
        if cal_ctx.get("is_year_end"):
            mcap = self._safe(info.get("marketCap"))
            if mcap and mcap < 5e9:
                scores["t5"] = 80
            elif sector in ["small cap", "mid cap"]:
                scores["t5"] = 78
            else:
                scores["t5"] = 65
        elif cal_ctx.get("is_january"):
            scores["t5"] = 75
        else:
            scores["t5"] = 65

        weights = {"t1": 0.20, "t2": 0.22, "t3": 0.18, "t4": 0.15, "t5": 0.25}
        return sum(scores[k] * weights[k] for k in weights), scores

    # ── Rule 7: Interest Rate Regime ─────────────────────────────────────────────
    def rule7(self, d, fed_regime=None):
        """
        10Y Treasury yield level + direction. Modulates score based on:
        - VERY_TIGHT (>5.0%): penalize high-P/E growth, reward value
        - RESTRICTIVE (4.5–5.0%): banks benefit, long-duration growth hurt
        - NEUTRAL (3.5–4.5%): balanced
        - ACCOMMODATIVE (<3.5%): growth stocks re-rate higher, REITs/utilities boosted
        """
        if fed_regime is None:
            fed_regime = self._get_fed_regime()

        info = d["info"]
        scores = {}
        sym = (info.get("symbol") or "").upper()
        pe = self._safe(info.get("trailingPE"))
        beta = self._safe(info.get("beta"))
        sector = (info.get("sector") or "").lower()

        ten_yr = fed_regime.get("ten_year")
        regime = fed_regime.get("regime", "NEUTRAL")
        rate_dir = fed_regime.get("rate_direction", "STABLE")

        if ten_yr:
            if "VERY_TIGHT" in regime or "RESTRICTIVE" in regime:
                if pe and pe > 30:
                    scores["t6"] = max(30, 75 - (pe - 30) * 1.5)
                elif pe and pe < 20:
                    scores["t6"] = 80  # value scores well
                else:
                    scores["t6"] = 65
                # Banks get boost from steep yield curve
                bank_syms = ["BAC", "JPM", "GS", "C", "MS", "KEY", "MTB", "USB", "TFC"]
                if sym in bank_syms:
                    scores["t6"] = 88
                # REITs/utilities penalized
                rate_sens = ["VNQ", "XLRE", "IYR", "XLU"]
                if sym in rate_sens:
                    scores["t6"] = max(25, scores["t6"] - 25)
            elif "ACCOMMODATIVE" in regime:
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

        # t7: Rate direction (rising/falling yields)
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

        weights = {"t6": 0.55, "t7": 0.45}
        return sum(scores[k] * weights[k] for k in weights), scores

    def _get_calendar_context(self):
        """Compute current calendar context (earnings/FOMC/macro windows)."""
        from datetime import datetime
        now = datetime.now()
        month, day, weekday = now.month, now.day, now.weekday()

        FOMC_WINDOWS = [
            (1, 28, 31), (3, 17, 20), (5, 5, 8), (6, 16, 19),
            (7, 28, 31), (9, 16, 19), (10, 6, 9), (12, 15, 18),
        ]
        EARNINGS_SEASONS = [
            (1, 8, 21), (4, 8, 21), (7, 8, 21), (10, 8, 21),
        ]
        ECON_RELEASE_WINDOWS = [(m, 5, 12) for m in range(1, 13)]

        in_earnings_season = any(m == month and s <= day <= e for m, s, e in EARNINGS_SEASONS)
        in_fomc_week = any(m == month and (e - 2) <= day <= (e + 1) for m, _, e in FOMC_WINDOWS)
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

        days_into_earnings = 0
        for m, s, e in EARNINGS_SEASONS:
            if m == month and s <= day <= e:
                days_into_earnings = day - s

        # FOMC risk: how many days to next meeting
        fomc_risk = 0
        for m, d, e in FOMC_WINDOWS:
            if m == month:
                dist = d - day
                if 0 <= dist <= 14:
                    fomc_risk = 1 - (dist / 14)

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
            "days_into_earnings": days_into_earnings,
            "fomc_risk": fomc_risk,
        }

    def _get_fed_regime(self):
        """Fetch current 10Y Treasury yield and determine rate regime + direction."""
        try:
            import yfinance as yf
            fi_10 = yf.Ticker("^TNX").fast_info
            ten_yr = getattr(fi_10, "last_price", None)
        except Exception:
            ten_yr = None

        rate_data = {"ten_year": None, "regime": "NEUTRAL", "rate_direction": "STABLE"}

        if ten_yr:
            rate_data["ten_year"] = round(float(ten_yr), 3)
            if ten_yr > 5.0:
                rate_data["regime"] = "VERY_TIGHT"
            elif ten_yr > 4.5:
                rate_data["regime"] = "RESTRICTIVE"
            elif ten_yr > 3.5:
                rate_data["regime"] = "NEUTRAL"
            else:
                rate_data["regime"] = "ACCOMMODATIVE"

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

        return rate_data

    # ── COMPOSITE SCORE ──────────────────────────────────────────────────────
    def composite(self, r1, r2, r3, r4, r5, r6, r7, cal_ctx=None, fed_regime=None):
        """
        Composite = weighted blend of 7 rules.
        Calendar pressure compresses scores toward 50 during high-vol windows.
        VERY_TIGHT/RESTRICTIVE regimes apply additional compression on growth stocks.
        """
        if cal_ctx is None:
            cal_ctx = self._get_calendar_context()
        if fed_regime is None:
            fed_regime = self._get_fed_regime()

        base = r1 * 0.20 + r2 * 0.16 + r3 * 0.12 + r4 * 0.08 + r5 * 0.28 + r6 * 0.10 + r7 * 0.06

        midpoint = 50
        pressure = cal_ctx.get("calendar_pressure", 0)
        if pressure > 0:
            compression = min(0.12, pressure * 0.20)
            base = midpoint + (base - midpoint) * (1.0 - compression)

        regime = fed_regime.get("regime", "NEUTRAL")
        if "VERY_TIGHT" in regime:
            base = midpoint + (base - midpoint) * 0.92
        elif "RESTRICTIVE" in regime:
            base = midpoint + (base - midpoint) * 0.96

        return {
            "composite_score": base,
            "rule1": round(r1, 1),
            "rule2": round(r2, 1),
            "rule3": round(r3, 1),
            "rule4": round(r4, 1),
            "rule5": round(r5, 1),
            "rule6": round(r6, 1),
            "rule7": round(r7, 1),
        }

    def score(self, symbol, tier="quick"):
        """Score a single stock across all 7 rules. Returns dict with all scores."""
        d = self._get_ticker(symbol)
        if "error" in d and d["error"]:
            return {"symbol": symbol, "error": d["error"]}

        cal_ctx = self._get_calendar_context()
        fed_regime = self._get_fed_regime()

        r1, r1_detail = self.rule1(d)
        r2, r2_detail = self.rule2(d)
        r3, r3_detail = self.rule3(d)
        r4, r4_detail = self.rule4(d)
        r5, r5_detail = self.rule5(d)
        r6, r6_detail = self.rule6(d, cal_ctx)
        r7, r7_detail = self.rule7(d, fed_regime)
        comp = self.composite(r1, r2, r3, r4, r5, r6, r7, cal_ctx, fed_regime)

        info = d["info"]
        cp = self._safe(info.get("currentPrice"))
        high52 = self._safe(info.get("fiftyTwoWeekHigh"))

        cs = comp["composite_score"]
        if cs >= 65:
            status = "buy"
        elif cs >= 45:
            status = "hold"
        else:
            status = "avoid"

        result = {
            "symbol": symbol,
            "tier": tier,
            "score_date": time.strftime("%Y-%m-%d"),
            # Rule 1
            "f_rule1总分": round(r1, 1),
            "f_earning_quality": r1_detail.get("f1"),
            "f_growth_rate": r1_detail.get("f2"),
            "f_balance_sheet": r1_detail.get("f3"),
            "f_market_position": r1_detail.get("f4"),
            "f_profitability": r1_detail.get("f5"),
            # Rule 2
            "o_rule2总分": round(r2, 1),
            "o_pullback_depth": r2_detail.get("o1"),
            "o_mean_reversion": r2_detail.get("o2"),
            "o_sector_recovery": r2_detail.get("o3"),
            "o_sentiment_turn": r2_detail.get("o4"),
            "o_value_distance": r2_detail.get("o5"),
            # Rule 3
            "m_rule3总分": round(r3, 1),
            "m_sector_rotation": r3_detail.get("m1"),
            "m_macro_tailwind": r3_detail.get("m2"),
            "m_policy_benefit": r3_detail.get("m3"),
            "m_feed_flows": r3_detail.get("m4"),
            "m_market_cap": r3_detail.get("m5"),
            # Rule 4
            "p_rule4总分": round(r4, 1),
            "p_policy_exposure": r4_detail.get("p1"),
            "p_regulatory_risk": r4_detail.get("p2"),
            "p_subsidy_benefit": r4_detail.get("p3"),
            "p_trade_exposure": r4_detail.get("p4"),
            "p_geopolitical": r4_detail.get("p5"),
            # Rule 5
            "q_rule5总分": round(r5, 1),
            "q_trend_score": r5_detail.get("q1"),
            "q_momentum": r5_detail.get("q2"),
            "q_low_volatility": r5_detail.get("q3"),
            "q_relative_strength": r5_detail.get("q4"),
            "q_vol_profile": r5_detail.get("q5"),
            # Rule 6
            "t_rule6总分": round(r6, 1),
            "t_earnings_season": r6_detail.get("t1"),
            "t_fomc_week": r6_detail.get("t2"),
            "t_cpi_jobs": r6_detail.get("t3"),
            "t_pension_rebalance": r6_detail.get("t4"),
            "t_year_end": r6_detail.get("t5"),
            # Rule 7
            "i_rule7总分": round(r7, 1),
            "i_rate_regime": r7_detail.get("t6"),
            "i_rate_direction": r7_detail.get("t7"),
            **comp,
            "scan_status": status,
            "current_price": cp,
            "fifty_two_high": high52,
        }
        return result

    def save_score(self, result, conn=None):
        """Save a score result to the database."""
        close_conn = conn is None
        if conn is None:
            conn = get_db()

        cols = list(result.keys())
        placeholders = ", ".join([f":{c}" for c in cols])
        insert_sql = f"INSERT OR REPLACE INTO scores ({', '.join(cols)}) VALUES ({placeholders})"
        conn.execute(insert_sql, result)

        if close_conn:
            conn.commit()
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# LIBRARY BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def get_universe():
    """
    Returns the full universe of stocks and ETFs to scan.
    In production this would pull from a data provider.
    For now, returns a solid starter universe of ~300 names.
    """
    stocks = [
        # Tech / AI (mega/large cap)
        "AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","AVGO","AMD","QCOM",
        "CRM","NOW","SNOW","UBER","LYFT","DASH","SQ","BLOCK","HOOD","PLTR",
        "INTC","TXN","ADI","ON","MRVL","PANW","CRWD","ZS","NET","DDOG",
        "KLAC","LRCX","AMAT","ASML","MU","Samsung","TSM","ASX",
        "MSFT","ADBE","ORCL","SAP","NOW","TEAM","WDAY","ZEN","FICO","CDNS",
        "PANW","FTNT","GEN","ZS","OKTA","CRWD","NET","AKAM","MIM","WIX",
        # Internet / Cloud
        "META","GOOGL","AMZN","NFLX","DIS","CMCSA","WBD","PARA","FOX",
        "SNAP","PINS","TWLO","TEAM","ROKU","MTCH","CHWY","CARRD","DLTR","COST",
        # Financials
        "JPM","BAC","WFC","GS","MS","C","BLK","AXP","V","MA","DFS","COF",
        "PYPL","SQ","BLOCK","AX","FI","NDAQ","ICE","CME","MET","PRU","TRV","ALL",
        # Healthcare
        "LLY","UNH","JNJ","ABBV","PFE","MRK","TMO","ABT","DHR","AMGN","GILD",
        "BMY","CVS","AMAT","IDXX","ISRG","DXCM","EW","REGN","VRTX","BIIB","MRNA",
        # Industrials
        "CAT","DE","BA","HON","UPS","FDX","RTX","LMT","NOC","GD","ITW","ETN",
        "EMR","ROK","PH","CMI","AME","TT","MAS","JCI","FAST","ROK","PCAR",
        # Consumer
        "AMZN","TSLA","HD","LOW","NKE","SBUX","MCD","TGT","WMT","COST","DG","DLTR",
        "BKNG","EXPE","MAR","HLT","RCL","CCL","NCLH","YUM","CMG","DPZ","PZZA",
        # Energy
        "XOM","CVX","COP","SLB","EOG","MPC","VLO","PSX","OXY","HAL","BKR","SLM",
        # Materials / Real Estate
        "LIN","APD","ECL","SHW","DD","NEM","FCX","AA","DOW","PPG","VMC","MLM",
        # Utilities / Telecom
        "NEE","DUK","SO","D","AEP","EXC","XEL","ED","PEG","AWK","CMS","WEC",
        "T","TMUS","VZ","CCI","AMT","EQIX","SPG","O","WELL","DLR","PSA",
    ]

    etfs = [
        # SPY/QQQ alternatives
        "SPY","QQQ","IWM","DIA","VTI","ITOT","SCHB","VEA","IEFA","EFA","EEM","IEMG",
        "VWO","IAGG","AGG","BND","BSV","VTIP","TIP","SCHZ","IEF",
        # Sector SPDRs
        "XLK","XLF","XLV","XLE","XLI","XLB","XLY","XLP","XLRE","XLU","XLC","XHB",
        # Semiconductor
        "SOXX","SMH","SOXQ","IGV","FPF","RXL","XSD","SFY","Cure","USD",
        # Tech/growth
        "QQQ","VGT","FTEC","IYW","XNT","SKYY","WCLD","CLOU","，云",
        "ARKK","ARKW","ARKQ","ARKF","PRNT","ANEW",
        "VB","VBR","VXF","SCHB","SPHB","SPHD","SPLG","DIA","MDY",
        # Dividends
        "VYM","DVY","SDY","HDV","SPHD","VIG","SCHD","DGRO","FENY","DVY",
        "JEPI","JEPQ","QYLD","XYLD","RPLY","USMV","SMLV","VBR",
        # Low Vol
        "SPLV","USMV","EFAV","EEMV","IEFAV","ACWV","CRBN","ALFA",
        "SPY","SPXL","SPXU","SSO","SDS","QID","QLD","TQQQ","SQQQ",
        # Gold / Commodities
        "GLD","IAU","SLV","CPER","UNG","uso","PDBC","DJP","com","IJH",
        # REITs
        "VNQ","SCHH","IYR","XLRE","O","SPG","AMT","CCI","EQIX","PSA","WELL",
        # International
        "VXUS","IXUS","SCHC","EEMA","EMXC","SPDW","SPFF","ISVZ","FLKR",
        # Leverage (small allocation)
        "SSO","SPXL","TQQQ","QID","SOXL","SOXS","LabU",
    ]

    return list(set(stocks + etfs))


def seed_universe():
    """Seed the library_queue with all stocks in the universe (priority=5)."""
    conn = get_db()
    universe = get_universe()
    today = time.strftime("%Y-%m-%d")

    inserted = 0
    for sym in universe:
        try:
            # Check if already exists
            cur = conn.execute("SELECT id FROM library_queue WHERE symbol = ?", (sym,)).fetchone()
            if not cur:
                conn.execute(
                    "INSERT INTO library_queue (symbol, tier, status, added_date, priority) VALUES (?, ?, ?, ?, ?)",
                    (sym, "quick", "pending", today, 5)
                )
                inserted += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    print(f"[{time_str()}] Seeded {inserted} symbols into library queue")
    return inserted


def time_str():
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


if __name__ == "__main__":
    import time as _time
    init_db()
    seed_universe()