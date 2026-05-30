#!/usr/bin/env python3
"""
Crypto Scoring Engine — BV Trader
Scoring system designed for 24/7 crypto trading (25% portfolio allocation target).

Uses:
  - yfinance (-USD suffix): price history, volume, moving averages
  - Coingecko API (free): market cap, supply, ATH, TVL, dev/community stats
  - DeFiLlama API (free): TVL for DeFi protocols

6 Rules adapted for crypto:
  Rule 1 — Crypto Fundamentals (22%): NVT ratio, supply maturity, tokenomics, on-chain activity
  Rule 2 — Opportunistic (18%): ATH pullback, mean reversion, social/dev sentiment, cycle position
  Rule 3 — Market Event (15%): sector rotation, macro tailwinds, volume surge, market cap tier
  Rule 4 — Narrative Alignment (10%): AI, DeFi, RWA, DePIN, meme, institutional adoption
  Rule 5 — Quantitative (35%): 200MA trend, 50/200 crossover, ATH distance, RS vs BTC, vol profile
  Rule 6 — Crypto Cycle + Fed (modulator): halving cycle, BTC dominance, funding rates, Fed regime
"""
import sys, os, time, json, requests
from datetime import datetime, timedelta

sys.path.insert(0, "/tmp/mkt_pkg")

DB_PATH = os.path.expanduser("~/.hermes/cron/output/wealth/portfolio.db")
TODAY = time.strftime("%Y-%m-%d")
TIMESTAMP = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

# ─── Crypto symbol mapping ───────────────────────────────────────────────────
# Library stores: BTC, ETH, SOL → yfinance needs: BTC-USD, ETH-USD, SOL-USD
# Coingecko needs: bitcoin, ethereum, solana
COINGECKO_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
    "LTC": "litecoin", "BCH": "bitcoin-cash", "DOGE": "dogecoin",
    "SHIB": "shiba-inu", "PEPE": "pepe", "WIF": "dogwifcoin",
    "BONK": "bonk", "LINK": "chainlink", "UNI": "uniswap",
    "AAVE": "aave", "CRV": "curve-dao-token", "SUSHI": "sushi",
    "YFI": "yearn-finance", "SKY": "skycoin", "ONDO": "ondo-finance",
    "PAXG": "pax-gold", "FIL": "filecoin", "HYPE": "hyperliquid",
    "ARB": "arbitrum", "POL": "polygon-ecosystem-token", "DOT": "polkadot",
    "AVAX": "avalanche-2", "ADA": "cardano", "LDO": "lido-dao",
    "BAT": "basic-attention-token", "XTZ": "tezos", "USDG": "goeuro",
    "TRUMP": "official-trump", "USDT": "tether", "USDC": "usd-coin",
    "RENDER": "render-token", "GRT": "the-graph",
}

# Sector tags for crypto (since yfinance returns None)
CRYPTO_SECTORS = {
    "BTC": ("Blue Chip", "Store of Value"),
    "ETH": ("Blue Chip", "Smart Contract Platform"),
    "SOL": ("Blue Chip", "Smart Contract Platform"),
    "XRP": ("Payments", "Cross-border Payments"),
    "LTC": ("Payments", "Digital Silver"),
    "BCH": ("Payments", "Peer-to-Peer Cash"),
    "DOGE": ("Meme", "Meme Coin"),
    "SHIB": ("Meme", "Meme Ecosystem"),
    "PEPE": ("Meme", "Meme Coin"),
    "WIF": ("Meme", "Solana Meme"),
    "BONK": ("Meme", "Solana Meme"),
    "LINK": ("DeFi", "Oracle Network"),
    "UNI": ("DeFi", "DEX"),
    "AAVE": ("DeFi", "Lending Protocol"),
    "CRV": ("DeFi", "DEX/Stableswap"),
    "SUSHI": ("DeFi", "DEX"),
    "YFI": ("DeFi", "Yield Aggregator"),
    "SKY": ("DeFi", "Yield Protocol"),
    "ONDO": ("RWA", "Tokenized Treasuries"),
    "PAXG": ("RWA", "Tokenized Gold"),
    "FIL": ("DePIN", "Decentralized Storage"),
    "HYPE": ("DePIN", "Perpetuals DEX"),
    "ARB": ("Layer 2", "Optimistic Rollup"),
    "POL": ("Layer 2", "ZK Rollup"),
    "DOT": ("Interoperability", "Parachain Network"),
    "AVAX": ("Interoperability", "Subnet Platform"),
    "ADA": ("Interoperability", "Research Blockchain"),
    "LDO": ("Governance", "Liquid Staking"),
    "BAT": ("Governance", "Ad Token"),
    "XTZ": ("Governance", "PoS Blockchain"),
    "USDG": ("Stablecoin", "Euro Stablecoin"),
    "TRUMP": ("Political", "PolitiFi"),
    "USDT": ("Stablecoin", "USD Stablecoin"),
    "USDC": ("Stablecoin", "USD Stablecoin"),
    "RENDER": ("AI", "GPU Rendering Network"),
    "GRT": ("AI", "Indexing Protocol"),
}

# ─── Data Fetchers ───────────────────────────────────────────────────────────

def fetch_yf(symbol):
    """Fetch yfinance data with -USD suffix for crypto."""
    import yfinance as yf
    yf_sym = f"{symbol}-USD"
    try:
        t = yf.Ticker(yf_sym)
        info = t.info or {}
        try:
            hist = t.history(period="1y", interval="1d")
        except:
            hist = None
        return {"info": info, "hist": hist, "symbol": yf_sym}
    except Exception as e:
        return {"info": {}, "hist": None, "symbol": yf_sym, "error": str(e)}


def fetch_coingecko(symbol, retries=2):
    """Fetch Coingecko data for a crypto symbol."""
    cg_id = COINGECKO_MAP.get(symbol, symbol.lower())
    for attempt in range(retries + 1):
        try:
            r = requests.get(
                f"https://api.coingecko.com/api/v3/coins/{cg_id}",
                params={"localization": "false", "tickers": "false",
                        "community_data": "true", "developer_data": "true",
                        "market_data": "true"},
                timeout=15
            )
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
        except Exception:
            time.sleep(1)
    return {}


def fetch_defi_llama(protocol_name=None):
    """Fetch TVL from DeFiLlama."""
    try:
        if protocol_name:
            r = requests.get(f"https://api.llama.fi/protocol/{protocol_name}", timeout=10)
            return r.json() if r.status_code == 200 else {}
        else:
            # Get all protocols
            r = requests.get("https://api.llama.fi/protocols", timeout=15)
            return r.json() if r.status_code == 200 else []
    except Exception:
        return {} if protocol_name else []


# ─── Crypto Scoring Rules ────────────────────────────────────────────────────

class CryptoScoreEngine:
    """Scoring engine designed specifically for crypto assets."""

    def _f(self, val, default=0.0):
        if val is None or (isinstance(val, float) and val != val):
            return default
        try:
            return float(val)
        except:
            return default

    def _price(self, info):
        """Get current price from yfinance info."""
        for key in ["currentPrice", "regularMarketPrice"]:
            v = info.get(key)
            if v is not None and isinstance(v, (int, float)) and 0 < v < 1_000_000:
                return float(v)
        return None

    # ── Rule 1: Crypto Fundamentals (22%) ──────────────────────────────────
    # Replaces stock fundamentals (P/E, EPS, margins) with crypto-native metrics
    def rule1(self, symbol, yf_data, cg_data):
        """
        Crypto fundamentals:
        - f1: NVT ratio (Network Value to Transactions) — like P/E for crypto
        - f2: Supply maturity — % of max supply already minted
        - f3: Tokenomics quality — deflationary, fixed supply, or inflationary
        - f4: On-chain activity — dev activity, community strength
        - f5: Protocol value — TVL (for DeFi) or network revenue
        """
        scores = {}
        info = yf_data.get("info", {})
        md = cg_data.get("market_data", {})
        dev = cg_data.get("developer_data", {})
        comm = cg_data.get("community_data", {})

        # f1: NVT Ratio (Market Cap / Daily Tx Volume) — lower = undervalued
        # Like P/E: NVT < 20 = cheap, NVT > 100 = expensive
        mcap = self._f(md.get("market_cap", {}).get("usd"))
        daily_vol = self._f(md.get("total_volume", {}).get("usd"))
        if mcap > 0 and daily_vol > 0:
            nvt = mcap / daily_vol
            # NVT 10-30 = great, 30-60 = fair, 60-100 = expensive, 100+ = overvalued
            if nvt < 20:
                scores["f1"] = 90
            elif nvt < 35:
                scores["f1"] = 80
            elif nvt < 60:
                scores["f1"] = 65
            elif nvt < 100:
                scores["f1"] = 45
            else:
                scores["f1"] = max(20, 70 - nvt * 0.3)
        else:
            scores["f1"] = 50  # default

        # f2: Supply maturity — % of max supply already in circulation
        circulating = self._f(md.get("circulating_supply"))
        max_supply = self._f(md.get("max_supply"))
        if max_supply > 0 and circulating > 0:
            supply_pct = circulating / max_supply
            # Higher maturity = more established, less inflation risk
            # But too high = most coins already mined (BTC at 95%)
            if supply_pct > 95:
                scores["f2"] = 85  # almost fully diluted, low inflation
            elif supply_pct > 80:
                scores["f2"] = 75
            elif supply_pct > 50:
                scores["f2"] = 60
            elif supply_pct > 20:
                scores["f2"] = 45
            else:
                scores["f2"] = 35  # high inflation risk
        elif max_supply == 0:
            # No max supply (ETH, DOGE) — moderate score
            scores["f2"] = 55
        else:
            scores["f2"] = 50

        # f3: Tokenomics quality
        # Check if deflationary, burn mechanism, or fixed supply
        total_supply = self._f(md.get("total_supply"))
        if max_supply > 0 and total_supply > max_supply:
            scores["f3"] = 20  # inflationary beyond max = bad
        elif max_supply > 0:
            scores["f3"] = 75  # fixed supply = good
        else:
            # No max supply — check if deflationary (burn > issuance)
            price_change_1y = self._f(md.get("price_change_percentage_1y"))
            if price_change_1y and price_change_1y > 0:
                scores["f3"] = 55  # at least positive price action
            else:
                scores["f3"] = 40

        # f4: Developer + Community activity
        forks = self._f(dev.get("forks"))
        stars = self._f(dev.get("stars"))
        contributors = self._f(dev.get("commit_count_4_weeks"))
        twitter = self._f(comm.get("twitter_followers"))
        reddit = self._f(comm.get("reddit_subscribers"))

        dev_score = 0
        if forks > 1000:
            dev_score += 30
        elif forks > 100:
            dev_score += 20
        elif forks > 10:
            dev_score += 10
        if stars > 10000:
            dev_score += 25
        elif stars > 1000:
            dev_score += 15
        elif stars > 100:
            dev_score += 8
        if contributors > 20:
            dev_score += 20
        elif contributors > 5:
            dev_score += 12
        elif contributors > 0:
            dev_score += 5

        social_score = 0
        if twitter > 1_000_000:
            social_score += 15
        elif twitter > 100_000:
            social_score += 10
        elif twitter > 10_000:
            social_score += 5
        if reddit > 500_000:
            social_score += 10
        elif reddit > 100_000:
            social_score += 6
        elif reddit > 10_000:
            social_score += 3

        scores["f4"] = min(100, dev_score + social_score)

        # f5: Protocol value (TVL for DeFi, network revenue for L1s)
        tvl_dict = md.get("total_value_locked") or {}
        tvl = self._f(tvl_dict.get("usd") if isinstance(tvl_dict, dict) else tvl_dict)
        mcap_to_tvl = self._f(md.get("mcap_to_tvl_ratio"))
        if tvl > 0 and mcap_to_tvl and mcap_to_tvl > 0:
            # MCap/TVL < 1 = undervalued, > 10 = overvalued
            if mcap_to_tvl < 0.5:
                scores["f5"] = 90
            elif mcap_to_tvl < 2:
                scores["f5"] = 75
            elif mcap_to_tvl < 5:
                scores["f5"] = 60
            elif mcap_to_tvl < 10:
                scores["f5"] = 45
            else:
                scores["f5"] = 30
        else:
            # No TVL data — use market cap as proxy for network value
            if mcap > 1e11:
                scores["f5"] = 80  # BTC/ETH tier
            elif mcap > 1e10:
                scores["f5"] = 65
            elif mcap > 1e9:
                scores["f5"] = 50
            else:
                scores["f5"] = 40

        weights = {"f1": 0.20, "f2": 0.15, "f3": 0.20, "f4": 0.25, "f5": 0.20}
        total = sum(scores[k] * weights[k] for k in weights)
        return total, scores

    # ── Rule 2: Opportunistic (18%) ────────────────────────────────────────
    # ATH pullback, mean reversion, social sentiment, cycle position
    def rule2(self, symbol, yf_data, cg_data):
        scores = {}
        info = yf_data.get("info", {})
        md = cg_data.get("market_data", {})
        cp = self._price(info) or 0
        high52 = self._f(info.get("fiftyTwoWeekHigh"))
        low52 = self._f(info.get("fiftyTwoWeekLow"))
        avg200 = self._f(info.get("twoHundredDayAverage"))
        avg50 = self._f(info.get("fiftyDayAverage"))

        ath = self._f(md.get("ath", {}).get("usd"))
        ath_change = self._f(md.get("ath_change_percentage", {}).get("usd"))

        # o1: ATH pullback depth — deeper = more opportunistic
        if ath > 0 and cp > 0:
            ath_pullback = ((ath - cp) / ath) * 100
            # 80%+ pullback = max opportunistic, 0% = no room
            if ath_pullback > 80:
                scores["o1"] = 85
            elif ath_pullback > 60:
                scores["o1"] = 75
            elif ath_pullback > 40:
                scores["o1"] = 60
            elif ath_pullback > 20:
                scores["o1"] = 45
            else:
                scores["o1"] = 30
        else:
            scores["o1"] = 50

        # o2: Mean reposition vs 200MA
        if avg200 and avg200 > 0 and cp > 0:
            distance = (cp - avg200) / avg200 * 100
            if distance > 50:
                scores["o2"] = 30  # overextended
            elif distance > 20:
                scores["o2"] = 50
            elif distance > 0:
                scores["o2"] = 70
            elif distance > -20:
                scores["o2"] = 75  # near support
            else:
                scores["o2"] = 85  # deep below MA = oversold
        else:
            scores["o2"] = 50

        # o3: Social sentiment — use price momentum as proxy + dev activity
        # (Coingecko sentiment data is limited; use price momentum + dev commits)
        change_7d = self._f(md.get("price_change_percentage_7d"))
        change_30d = self._f(md.get("price_change_percentage_30d"))
        dev = cg_data.get("developer_data", {})
        commits = self._f(dev.get("commit_count_4_weeks"))

        momentum = 0
        if change_7d and change_30d:
            if change_7d > 0 and change_30d > 0:
                momentum = 80  # both positive
            elif change_7d > 0:
                momentum = 65  # short-term positive
            elif change_30d > 0:
                momentum = 55  # medium-term positive
            else:
                momentum = 35  # both negative
        else:
            momentum = 50

        dev_boost = min(15, commits * 0.3) if commits > 0 else 0
        scores["o3"] = min(100, momentum + dev_boost)

        # o4: Cycle position — where are we in the 4-year cycle?
        # Use BTC halving as reference
        btc_halving_dates = [
            datetime(2012, 11, 28),
            datetime(2016, 7, 9),
            datetime(2020, 5, 11),
            datetime(2024, 4, 20),
        ]
        now = datetime.now()
        last_halving = max(h for h in btc_halving_dates if h < now)
        days_since_halving = (now - last_halving).days
        # Halving cycle: 0-180 days = accumulation, 180-365 = early bull,
        # 365-550 = mid bull, 550-730 = late bull/bear start, 730-1460 = bear
        if days_since_halving < 180:
            scores["o4"] = 70  # accumulation phase
        elif days_since_halving < 365:
            scores["o4"] = 85  # early bull = good entry
        elif days_since_halving < 550:
            scores["o4"] = 65  # mid bull = cautious
        elif days_since_halving < 730:
            scores["o4"] = 40  # late bull = risky
        else:
            scores["o4"] = 55  # bear = accumulation opportunity

        # o5: Value distance — price vs 52-week range position
        if high52 and low52 and high52 != low52:
            range_pos = (cp - low52) / (high52 - low52)
            # Lower = more value, higher = expensive
            scores["o5"] = max(10, 90 - range_pos * 80)
        else:
            scores["o5"] = 50

        weights = {"o1": 0.25, "o2": 0.20, "o3": 0.20, "o4": 0.20, "o5": 0.15}
        total = sum(scores[k] * weights[k] for k in weights)
        return total, scores

    # ── Rule 3: Market Event (15%) ─────────────────────────────────────────
    # Crypto sector rotation, macro tailwinds, volume, market cap
    def rule3(self, symbol, yf_data, cg_data):
        scores = {}
        info = yf_data.get("info", {})
        md = cg_data.get("market_data", {})

        # m1: Sector rotation — which crypto sectors are hot?
        # Use our manual sector mapping since yfinance returns None
        sector = CRYPTO_SECTORS.get(symbol, ("Unknown", "Unknown"))[0]
        # Current favored sectors (can be updated based on market conditions)
        favored = ["Blue Chip", "AI", "DeFi", "RWA", "DePIN"]
        neutral = ["Payments", "Layer 2", "Interoperability"]
        disfavored = ["Meme", "Political", "Stablecoin", "Governance"]

        if sector in favored:
            scores["m1"] = 80
        elif sector in neutral:
            scores["m1"] = 60
        elif sector in disfavored:
            scores["m1"] = 35
        else:
            scores["m1"] = 50

        # m2: Macro tailwind — crypto benefits from:
        # - Loose monetary policy (low rates)
        # - BTC ETF approval (institutional flow)
        # - Regulatory clarity
        # We proxy this with 10Y yield regime (already in portfolio_manager)
        mcap = self._f(md.get("market_cap", {}).get("usd"))
        if mcap > 1e12:
            scores["m2"] = 90  # mega-cap, institutional grade
        elif mcap > 1e11:
            scores["m2"] = 80
        elif mcap > 1e10:
            scores["m2"] = 65
        elif mcap > 1e9:
            scores["m2"] = 50
        else:
            scores["m2"] = 35

        # m3: Volume surge — unusual volume = interest
        vol = self._f(info.get("averageVolume"))
        vol_today = self._f(info.get("volume"))
        if vol > 0 and vol_today > 0:
            vol_ratio = vol_today / vol
            if vol_ratio > 2.0:
                scores["m3"] = 90
            elif vol_ratio > 1.5:
                scores["m3"] = 75
            elif vol_ratio > 0.8:
                scores["m3"] = 60
            else:
                scores["m3"] = 40
        else:
            scores["m3"] = 55

        # m4: Protocol growth — check if price is trending up over 1y
        change_1y = self._f(md.get("price_change_percentage_1y"))
        if change_1y and change_1y > 100:
            scores["m4"] = 85
        elif change_1y and change_1y > 0:
            scores["m4"] = 65
        elif change_1y and change_1y > -20:
            scores["m4"] = 50
        else:
            scores["m4"] = 35

        # m5: Market cap tier (same as stocks but with crypto ranges)
        if mcap > 1e12:
            scores["m5"] = 95
        elif mcap > 1e11:
            scores["m5"] = 85
        elif mcap > 1e10:
            scores["m5"] = 70
        elif mcap > 1e9:
            scores["m5"] = 55
        else:
            scores["m5"] = 40

        weights = {"m1": 0.25, "m2": 0.20, "m3": 0.20, "m4": 0.20, "m5": 0.15}
        total = sum(scores[k] * weights[k] for k in weights)
        return total, scores

    # ── Rule 4: Narrative Alignment (10%) ──────────────────────────────────
    # AI, DeFi, RWA, DePIN, institutional adoption, regulatory tailwinds
    def rule4(self, symbol, yf_data, cg_data):
        scores = {}
        sector, industry = CRYPTO_SECTORS.get(symbol, ("Unknown", "Unknown"))

        # p1: Policy/narrative exposure
        # Favored narratives: AI crypto, RWA tokenization, DePIN, BTC ETF
        ai_syms = ["RENDER", "GRT", "FET", "TAO", "NEAR"]
        rwa_syms = ["ONDO", "PAXG", "MKR", "AAVE"]
        depin_syms = ["FIL", "HYPE", "RNDR", "AKT"]
        btc_proxy = ["BTC", "ETH"]

        if symbol in btc_proxy:
            scores["p1"] = 95  # BTC ETF = massive institutional flow
        elif symbol in ai_syms or "AI" in sector:
            scores["p1"] = 88  # AI narrative = hot
        elif symbol in rwa_syms or "RWA" in sector:
            scores["p1"] = 82  # RWA = growing narrative
        elif symbol in depin_syms or "DePIN" in sector:
            scores["p1"] = 78
        elif "DeFi" in sector:
            scores["p1"] = 70
        elif "Layer 2" in sector:
            scores["p1"] = 65
        elif "Meme" in sector:
            scores["p1"] = 40
        elif "Political" in sector:
            scores["p1"] = 30
        else:
            scores["p1"] = 55

        # p2: Regulatory risk
        # US regulatory clarity varies by asset type
        if symbol in ["BTC", "ETH"]:
            scores["p2"] = 90  # ETF approved = clear
        elif symbol == "SOL":
            scores["p2"] = 65  # ETF pending, some clarity
        elif sector == "Stablecoin":
            scores["p2"] = 75  # stablecoin regulation emerging
        elif sector in ["Meme", "Political"]:
            scores["p2"] = 40  # high regulatory uncertainty
        else:
            scores["p2"] = 55

        # p3: Institutional adoption potential
        if symbol in ["BTC", "ETH"]:
            scores["p3"] = 95
        elif symbol in ["SOL", "XRP", "ADA"]:
            scores["p3"] = 70
        elif "DeFi" in sector:
            scores["p3"] = 55
        elif "Meme" in sector:
            scores["p3"] = 25
        else:
            scores["p3"] = 50

        # p4: Decentralization score
        # More decentralized = more resilient
        if symbol in ["BTC", "ETH", "DOGE", "LTC"]:
            scores["p4"] = 90
        elif symbol in ["SOL", "ADA", "DOT"]:
            scores["p4"] = 75
        elif "Layer 2" in sector:
            scores["p4"] = 55  # depends on L1
        elif "DeFi" in sector:
            scores["p4"] = 70  # governance tokens vary
        else:
            scores["p4"] = 50

        # p5: Geopolitical hedge value
        # Crypto as hedge against inflation, currency debasement
        if symbol in ["BTC", "PAXG"]:
            scores["p5"] = 90  # digital gold / tokenized gold
        elif symbol == "ETH":
            scores["p5"] = 65  # digital oil + store of value
        elif sector == "Stablecoin":
            scores["p5"] = 50  # dollar proxy
        else:
            scores["p5"] = 40

        weights = {"p1": 0.30, "p2": 0.25, "p3": 0.20, "p4": 0.15, "p5": 0.10}
        total = sum(scores[k] * weights[k] for k in weights)
        return total, scores

    # ── Rule 5: Quantitative (35%) ─────────────────────────────────────────
    # Same structure as stocks but with crypto-specific calibrations
    def rule5(self, symbol, yf_data, cg_data):
        scores = {}
        info = yf_data.get("info", {})
        hist = yf_data.get("hist")
        cp = self._price(info) or 0
        high52 = self._f(info.get("fiftyTwoWeekHigh"))
        low52 = self._f(info.get("fiftyTwoWeekLow"))
        avg200 = self._f(info.get("twoHundredDayAverage"))
        avg50 = self._f(info.get("fiftyDayAverage"))

        # q1: Trend vs 200MA
        if avg200 and avg200 > 0 and cp > 0:
            distance = (cp - avg200) / avg200 * 100
            if distance > 30:
                scores["q1"] = 85  # strong uptrend
            elif distance > 10:
                scores["q1"] = 75
            elif distance > 0:
                scores["q1"] = 60
            elif distance > -10:
                scores["q1"] = 45
            else:
                scores["q1"] = 30  # below 200MA = downtrend
        else:
            scores["q1"] = 50

        # q2: Momentum (50MA vs 200MA)
        if avg50 and avg200 and avg50 > 0 and avg200 > 0:
            golden = avg50 > avg200
            distance = abs(avg50 - avg200) / avg200 * 100
            if golden and distance > 10:
                scores["q2"] = 85  # strong golden cross
            elif golden:
                scores["q2"] = 65
            elif distance > 10:
                scores["q2"] = 35  # strong death cross
            else:
                scores["q2"] = 50
        else:
            scores["q2"] = 50

        # q3: Low volatility / distance from ATH
        # Crypto is volatile, so we calibrate differently
        md = cg_data.get("market_data", {})
        ath = self._f(md.get("ath", {}).get("usd"))
        if ath > 0 and cp > 0:
            from_ath = ((ath - cp) / ath) * 100
            if from_ath < 10:
                scores["q3"] = 90  # near ATH = strong
            elif from_ath < 25:
                scores["q3"] = 75
            elif from_ath < 50:
                scores["q3"] = 55
            elif from_ath < 75:
                scores["q3"] = 40
            else:
                scores["q3"] = 25  # deep in bear
        else:
            scores["q3"] = 50

        # q4: Relative strength vs BTC
        # For non-BTC coins, compare 60-day performance vs BTC
        if symbol != "BTC" and hist is not None and len(hist) >= 60:
            try:
                current = float(hist["Close"].iloc[-1])
                start_60d = float(hist["Close"].iloc[-60])
                crypto_return = (current / start_60d - 1) * 100 if start_60d > 0 else 0

                # Fetch BTC performance for comparison
                btc_hist = yf_data.get("btc_hist")
                if btc_hist is not None and len(btc_hist) >= 60:
                    btc_current = float(btc_hist["Close"].iloc[-1])
                    btc_start = float(btc_hist["Close"].iloc[-60])
                    btc_return = (btc_current / btc_start - 1) * 100 if btc_start > 0 else 0
                    rs = crypto_return - btc_return
                    scores["q4"] = min(100, max(0, 50 + rs * 2))
                else:
                    scores["q4"] = 50
            except:
                scores["q4"] = 50
        else:
            # BTC itself — use absolute performance
            if hist is not None and len(hist) >= 60:
                try:
                    current = float(hist["Close"].iloc[-1])
                    start_60d = float(hist["Close"].iloc[-60])
                    ret = (current / start_60d - 1) * 100 if start_60d > 0 else 0
                    scores["q4"] = min(100, max(0, 50 + ret))
                except:
                    scores["q4"] = 50
            else:
                scores["q4"] = 50

        # q5: Volatility profile — crypto is inherently volatile
        # We want moderate volatility: not too wild, not dead
        if hist is not None and len(hist) >= 30:
            try:
                daily_returns = hist["Close"].pct_change().dropna()
                vol = daily_returns.std() * (252 ** 0.5)  # annualized
                # Crypto vol: 50-150% = normal, >200% = too wild, <30% = dead
                if 40 < vol < 120:
                    scores["q5"] = 75
                elif 30 < vol < 40 or 120 < vol < 200:
                    scores["q5"] = 55
                elif vol < 30:
                    scores["q5"] = 35  # too low = no trading opportunity
                else:
                    scores["q5"] = 30  # too high = dangerous
            except:
                scores["q5"] = 50
        else:
            scores["q5"] = 50

        weights = {"q1": 0.25, "q2": 0.25, "q3": 0.25, "q4": 0.15, "q5": 0.10}
        total = sum(scores[k] * weights[k] for k in weights)
        return total, scores

    # ── Rule 6: Crypto Cycle + Fed Regime (modulator) ──────────────────────
    # Halving cycle, BTC dominance, funding rates, Fed regime
    def rule6(self, symbol, yf_data, cg_data, cal_ctx=None, fed_regime=None):
        scores = {}
        info = yf_data.get("info", {})
        md = cg_data.get("market_data", {})
        sector = CRYPTO_SECTORS.get(symbol, ("Unknown", "Unknown"))[0]
        sym = symbol.upper()

        # t1: Halving cycle phase
        btc_halving_dates = [
            datetime(2012, 11, 28),
            datetime(2016, 7, 9),
            datetime(2020, 5, 11),
            datetime(2024, 4, 20),
        ]
        now = datetime.now()
        last_halving = max(h for h in btc_halving_dates if h < now)
        days_since = (now - last_halving).days

        if days_since < 180:
            scores["t1"] = 75  # post-halving accumulation
        elif days_since < 365:
            scores["t1"] = 85  # early bull — best time
        elif days_since < 550:
            scores["t1"] = 65  # mid bull — cautious
        elif days_since < 730:
            scores["t1"] = 40  # late bull — reduce exposure
        else:
            scores["t1"] = 55  # bear — start accumulating

        # t2: Fed regime impact on crypto
        # Crypto is macro-sensitive: low rates = bullish, high rates = bearish
        ten_yr = fed_regime.get("ten_year") if fed_regime else None
        regime = fed_regime.get("regime", "NEUTRAL") if fed_regime else "NEUTRAL"
        rate_dir = fed_regime.get("rate_direction", "STABLE") if fed_regime else "STABLE"

        if "ACCOMMODATIVE" in regime:
            scores["t2"] = 90  # low rates = crypto moon
        elif "NEUTRAL" in regime:
            scores["t2"] = 70
        elif "RESTRICTIVE" in regime:
            scores["t2"] = 50
        else:
            scores["t2"] = 35  # very tight = crypto crushed

        if rate_dir == "FALLING":
            scores["t2"] = min(100, scores["t2"] + 10)
        elif rate_dir == "RISING":
            scores["t2"] = max(20, scores["t2"] - 10)

        # t3: BTC dominance phase (simplified — proxy with BTC market cap share)
        # When BTC dominance rising → risk off, when falling → alt season
        btc_mcap = self._f(md.get("market_cap", {}).get("usd")) if sym == "BTC" else 0
        if sym == "BTC":
            scores["t3"] = 80  # BTC always gets a boost during uncertainty
        elif sector == "Blue Chip":
            scores["t3"] = 65
        elif sector in ["Meme", "Political"]:
            scores["t3"] = 50  # alts only pump in alt season
        else:
            scores["t3"] = 55

        # t4: FOMC risk (crypto reacts to Fed decisions)
        if cal_ctx and cal_ctx.get("in_fomc_week"):
            scores["t4"] = 50  # reduce conviction during FOMC
        elif cal_ctx and cal_ctx.get("fomc_risk", 0) > 0.5:
            scores["t4"] = 60
        else:
            scores["t4"] = 70

        # t5: Crypto-specific seasonality
        # Historical: Q4 often strong, January effect exists in crypto too
        month = now.month
        if month in [10, 11, 12]:
            scores["t5"] = 80  # Q4 historically strong
        elif month in [1, 2]:
            scores["t5"] = 75  # January effect
        elif month in [3, 4]:
            scores["t5"] = 60  # spring chop
        elif month in [5, 6, 7]:
            scores["t5"] = 50  # summer doldrums
        else:
            scores["t5"] = 65

        weights = {"t1": 0.25, "t2": 0.25, "t3": 0.15, "t4": 0.15, "t5": 0.20}
        total = sum(scores[k] * weights[k] for k in weights)
        return total, scores

    # ── Composite ──────────────────────────────────────────────────────────
    def composite(self, r1, r2, r3, r4, r5, r6, cal_ctx=None, fed_regime=None):
        # Base composite (same weights as stocks)
        base = r1 * 0.22 + r2 * 0.18 + r3 * 0.15 + r4 * 0.10 + r5 * 0.35

        # Crypto has no earnings season / pension rebalance → less compression
        # But we still compress during FOMC/high-pressure windows
        if cal_ctx:
            pressure = cal_ctx.get("calendar_pressure", 0)
            if pressure > 0:
                compression = min(0.10, pressure * 0.12)
                base = 50 + (base - 50) * (1.0 - compression)

        # Fed regime: crypto is MORE sensitive to rates than stocks
        regime = fed_regime.get("regime", "NEUTRAL") if fed_regime else "NEUTRAL"
        if "VERY_TIGHT" in regime:
            base = 50 + (base - 50) * 0.88  # crypto drops harder
        elif "ACCOMMODATIVE" in regime:
            base = 50 + (base - 50) * 1.08  # crypto pumps harder

        return base

    # ── Full scoring pipeline ──────────────────────────────────────────────
    def score(self, symbol):
        """Score a single crypto symbol."""
        yf_data = fetch_yf(symbol)
        cg_data = fetch_coingecko(symbol)

        # Validate yfinance data - some symbols have ticker collisions
        info = yf_data.get("info", {})
        yf_price = self._price(info)
        cg_price = self._f(cg_data.get("market_data", {}).get("current_price", {}).get("usd"))

        # If yfinance price is wildly different from Coingecko, skip yfinance
        if yf_price and cg_price and cg_price > 0:
            ratio = yf_price / cg_price
            if ratio < 0.5 or ratio > 2.0:
                # Ticker collision - skip yfinance data
                yf_data = {"info": {}, "hist": None, "symbol": f"{symbol}-USD (skipped)", "error": "ticker collision"}

        if not yf_data.get("info") and not cg_data:
            return {"symbol": symbol, "error": "No data from yfinance or Coingecko"}
        elif not yf_data.get("info"):
            # No yfinance data - use Coingecko only (limited technical scoring)
            yf_data = {"info": {"currentPrice": cg_price} if cg_price else {}, "hist": None, "symbol": f"{symbol}-USD"}

        r1, r1d = self.rule1(symbol, yf_data, cg_data)
        r2, r2d = self.rule2(symbol, yf_data, cg_data)
        r3, r3d = self.rule3(symbol, yf_data, cg_data)
        r4, r4d = self.rule4(symbol, yf_data, cg_data)
        r5, r5d = self.rule5(symbol, yf_data, cg_data)
        r6, r6d = self.rule6(symbol, yf_data, cg_data)

        # Import calendar/fed context from portfolio_manager
        try:
            from portfolio_manager import CAL_CONTEXT, FED_REGIME_MGR
        except ImportError:
            CAL_CONTEXT = {}
            FED_REGIME_MGR = {}

        cs = self.composite(r1, r2, r3, r4, r5, r6, CAL_CONTEXT, FED_REGIME_MGR)

        cp = self._price(yf_data.get("info", {}))
        md = cg_data.get("market_data", {})
        ath = self._f(md.get("ath", {}).get("usd"))

        # Crypto has higher volatility → wider thresholds
        # BUY: 60 (lower than stocks because crypto is inherently riskier)
        # HOLD: 40-59
        # AVOID: below 40
        if cs >= 60:
            status = "buy"
        elif cs >= 40:
            status = "hold"
        else:
            status = "avoid"

        return {
            "symbol": symbol,
            "asset_type": "crypto",
            "score_date": TODAY,
            "tier": "crypto",
            # Rule 1: Crypto Fundamentals (mapped to existing column names)
            "f_earning_quality": r1d.get("f1"),        # NVT ratio
            "f_growth_rate": r1d.get("f2"),            # Supply maturity
            "f_balance_sheet": r1d.get("f3"),          # Tokenomics
            "f_market_position": r1d.get("f4"),        # Dev/community
            "f_profitability": r1d.get("f5"),          # Protocol value
            "f_rule1总分": round(r1, 1),
            # Rule 2: Opportunistic
            "o_pullback_depth": r2d.get("o1"),         # ATH pullback
            "o_mean_reversion": r2d.get("o2"),         # Mean reversion
            "o_sector_recovery": r2d.get("o3"),        # Social sentiment
            "o_sentiment_turn": r2d.get("o4"),         # Cycle position
            "o_value_distance": r2d.get("o5"),         # Value distance
            "o_rule2总分": round(r2, 1),
            # Rule 3: Market Event
            "m_sector_rotation": r3d.get("m1"),        # Sector rotation
            "m_macro_tailwind": r3d.get("m2"),         # Macro tailwind
            "m_policy_benefit": r3d.get("m3"),         # Volume surge
            "m_feed_flows": r3d.get("m4"),             # Protocol growth
            "m_market_cap": r3d.get("m5"),             # Market cap tier
            "m_rule3总分": round(r3, 1),
            # Rule 4: Narrative
            "p_policy_exposure": r4d.get("p1"),        # Narrative exposure
            "p_regulatory_risk": r4d.get("p2"),        # Regulatory risk
            "p_subsidy_benefit": r4d.get("p3"),        # Institutional adoption
            "p_trade_exposure": r4d.get("p4"),         # Decentralization
            "p_geopolitical": r4d.get("p5"),           # Geopolitical hedge
            "p_rule4总分": round(r4, 1),
            # Rule 5: Quantitative
            "q_trend_score": r5d.get("q1"),
            "q_momentum": r5d.get("q2"),
            "q_low_volatility": r5d.get("q3"),         # ATH distance
            "q_relative_strength": r5d.get("q4"),
            "q_vol_profile": r5d.get("q5"),
            "q_rule5总分": round(r5, 1),
            # Rule 6: Cycle + Fed
            "rule1": round(r1, 1),
            "rule2": round(r2, 1),
            "rule3": round(r3, 1),
            "rule4": round(r4, 1),
            "rule5": round(r5, 1),
            "rule6": round(r6, 1),
            "t_earnings_season": r6d.get("t1"),        # Halving cycle
            "t_fomc_risk": r6d.get("t2"),              # Fed regime
            "t_macro_week": r6d.get("t3"),             # BTC dominance
            "t_pension_rebalance": r6d.get("t4"),      # FOMC risk
            "t_year_end": r6d.get("t5"),               # Seasonality
            "t_rule6总分": round(r6, 1),
            # Composite
            "composite_score": round(cs, 1),
            "scan_status": status,
            "current_price": cp,
            "fifty_two_high": ath,
            "calendar_pressure": CAL_CONTEXT.get("calendar_pressure", 0) if CAL_CONTEXT else 0,
            "in_earnings_season": CAL_CONTEXT.get("in_earnings_season", 0) if CAL_CONTEXT else 0,
            "in_fomc_week": CAL_CONTEXT.get("in_fomc_week", 0) if CAL_CONTEXT else 0,
            "in_macro_week": CAL_CONTEXT.get("in_macro_week", 0) if CAL_CONTEXT else 0,
            "in_pension_rebalance": CAL_CONTEXT.get("in_pension_rebalance", 0) if CAL_CONTEXT else 0,
            "buy_threshold": 60,
            "sell_threshold": 40,
            "fed_ten_year": FED_REGIME_MGR.get("ten_year") if FED_REGIME_MGR else None,
            "fed_regime": FED_REGIME_MGR.get("regime") if FED_REGIME_MGR else None,
            "fed_rate_direction": FED_REGIME_MGR.get("rate_direction") if FED_REGIME_MGR else None,
            "fed_fomc_countdown": FED_REGIME_MGR.get("fomc_countdown") if FED_REGIME_MGR else None,
            "fed_spread_10y2y": FED_REGIME_MGR.get("spread_10y2y") if FED_REGIME_MGR else None,
        }

    def save(self, result):
        """Save score to portfolio.db."""
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cols = list(result.keys())
        placeholders = ", ".join([f":{c}" for c in cols])
        sql = f"INSERT OR REPLACE INTO scores ({', '.join(cols)}) VALUES ({placeholders})"
        conn.execute(sql, result)
        conn.commit()
        conn.close()


# ─── Batch scoring ───────────────────────────────────────────────────────────

def score_crypto_batch(symbols):
    """Score multiple crypto symbols with rate limit handling."""
    engine = CryptoScoreEngine()
    results = []
    errors = []

    for i, sym in enumerate(symbols):
        print(f"  [{i+1}/{len(symbols)}] Scoring {sym}...", end=" ", flush=True)
        try:
            result = engine.score(sym)
            if "error" not in result:
                engine.save(result)
                results.append(f"{sym}({result['composite_score']:.1f}) [{result['scan_status']}]")
                print(f"✓ CS={result['composite_score']:.1f} [{result['scan_status']}]")
            else:
                errors.append(f"{sym}: {result['error']}")
                print(f"✗ {result['error']}")
        except Exception as e:
            errors.append(f"{sym}: {e}")
            print(f"✗ {e}")

        # Rate limit: Coingecko free API ~10-30 req/min
        if i < len(symbols) - 1:
            time.sleep(1.5)  # optimized for batch scoring

    return results, errors


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Test on sample cryptos")
    parser.add_argument("--batch", nargs="+", help="Score specific symbols")
    parser.add_argument("--all", action="store_true", help="Score all crypto in library")
    args = parser.parse_args()

    if args.test:
        engine = CryptoScoreEngine()
        for sym in ["BTC", "ETH", "SOL", "LINK", "DOGE"]:
            r = engine.score(sym)
            if "error" not in r:
                print(f"\n{sym}:")
                print(f"  R1={r['rule1']:5.1f} R2={r['rule2']:5.1f} R3={r['rule3']:5.1f} "
                      f"R4={r['rule4']:5.1f} R5={r['rule5']:5.1f} R6={r['rule6']:5.1f}")
                print(f"  CS={r['composite_score']:5.1f} [{r['scan_status']}]")
                print(f"  Price: ${r['current_price']:,.2f} | ATH: ${r['fifty_two_high']:,.0f}")
            else:
                print(f"{sym}: ERROR — {r['error']}")
            time.sleep(3)

    elif args.batch:
        results, errors = score_crypto_batch(args.batch)
        print(f"\n✅ Scored: {len(results)}")
        for r in results:
            print(f"  {r}")
        if errors:
            print(f"\n❌ Errors: {len(errors)}")
            for e in errors:
                print(f"  {e}")

    elif args.all:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        symbols = [r[0] for r in conn.execute(
            "SELECT symbol FROM stocks WHERE asset_type='crypto' ORDER BY symbol"
        ).fetchall()]
        conn.close()
        print(f"Scoring {len(symbols)} crypto symbols...")
        results, errors = score_crypto_batch(symbols)
        print(f"\n✅ Scored: {len(results)} | ❌ Errors: {len(errors)}")

    else:
        parser.print_help()
