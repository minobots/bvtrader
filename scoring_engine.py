#!/usr/local/bin/python3
"""
Quick Triage Scoring Engine — 25 metrics across 5 strategic rules
Each stock gets scored 0-100 per rule, then composite.

Rule 1 (Fundamental): Quality, earnings power, balance sheet
Rule 2 (Opportunistic): Pullback depth, mean reversion, sector recovery
Rule 3 (Market Event): Sector rotation, macro catalysts, policy
Rule 4 (Political Alignment): Policy beneficiaries/risk, geopolitics
Rule 5 (Quantitative): Trend, momentum, low vol, relative strength

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

    # ── COMPOSITE SCORE ──────────────────────────────────────────────────────
    def composite(self, r1, r2, r3, r4, r5):
        """
        Composite = weighted blend of 5 rules.
        Conviction stocks (top 20): equal weight.
        Library stocks: rule 1+5 weighted more (quality + trend).
        """
        return {
            "composite_score": r1 * 0.22 + r2 * 0.18 + r3 * 0.15 + r4 * 0.10 + r5 * 0.35,
            "rule1": round(r1, 1),
            "rule2": round(r2, 1),
            "rule3": round(r3, 1),
            "rule4": round(r4, 1),
            "rule5": round(r5, 1),
        }

    def score(self, symbol, tier="quick"):
        """Score a single stock. Returns dict with all scores."""
        d = self._get_ticker(symbol)
        if "error" in d and d["error"]:
            return {"symbol": symbol, "error": d["error"]}

        r1, r1_detail = self.rule1(d)
        r2, r2_detail = self.rule2(d)
        r3, r3_detail = self.rule3(d)
        r4, r4_detail = self.rule4(d)
        r5, r5_detail = self.rule5(d)
        comp = self.composite(r1, r2, r3, r4, r5)

        info = d["info"]
        cp = self._safe(info.get("currentPrice"))
        high52 = self._safe(info.get("fiftyTwoWeekHigh"))

        # Scan status: BUY if composite >= 60, HOLD if >= 40, AVOID if < 40
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
            "f_rule1总分": round(r1, 1),
            "f_earning_quality": r1_detail.get("f1"),
            "f_growth_rate": r1_detail.get("f2"),
            "f_balance_sheet": r1_detail.get("f3"),
            "f_market_position": r1_detail.get("f4"),
            "f_profitability": r1_detail.get("f5"),
            "o_rule2总分": round(r2, 1),
            "o_pullback_depth": r2_detail.get("o1"),
            "o_mean_reversion": r2_detail.get("o2"),
            "o_sector_recovery": r2_detail.get("o3"),
            "o_sentiment_turn": r2_detail.get("o4"),
            "o_value_distance": r2_detail.get("o5"),
            "m_rule3总分": round(r3, 1),
            "m_sector_rotation": r3_detail.get("m1"),
            "m_macro_tailwind": r3_detail.get("m2"),
            "m_policy_benefit": r3_detail.get("m3"),
            "m_feed_flows": r3_detail.get("m4"),
            "m_market_cap": r3_detail.get("m5"),
            "p_rule4总分": round(r4, 1),
            "p_policy_exposure": r4_detail.get("p1"),
            "p_regulatory_risk": r4_detail.get("p2"),
            "p_subsidy_benefit": r4_detail.get("p3"),
            "p_trade_exposure": r4_detail.get("p4"),
            "p_geopolitical": r4_detail.get("p5"),
            "q_rule5总分": round(r5, 1),
            "q_trend_score": r5_detail.get("q1"),
            "q_momentum": r5_detail.get("q2"),
            "q_low_volatility": r5_detail.get("q3"),
            "q_relative_strength": r5_detail.get("q4"),
            "q_vol_profile": r5_detail.get("q5"),
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