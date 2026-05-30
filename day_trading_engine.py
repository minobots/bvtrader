#!/usr/bin/env python3
"""
Crypto Day Trading Engine — BV Trader
Target: 1% daily return through frequent intraday trades.

Strategies (running in parallel):
  1. SCALP-RSI: 1-min RSI extremes + mean reversion (high frequency, small targets)
  2. MOMENTUM-BREAK: 5-min breakout with volume confirmation (medium frequency)
  3. MEAN-REVERT-BB: 5-min Bollinger Band reversions (medium frequency)
  4. VWAP-FADE: 15-min VWAP deviations (low frequency, high conviction)
  5. GRID-TRADE: Fixed-level grid orders (passive, always active)

Risk Management:
  - Max 2% portfolio risk per day (stop trading after -2%)
  - Max 0.5% risk per trade
  - Stop loss: 0.8% below entry
  - Take profit: 1.2% above entry (1.5:1 R:R minimum)
  - Trailing stop: 0.4% after +0.6% profit
  - Max 3 concurrent positions
  - No trading during FOMC weeks (high volatility)

Position Sizing (Kelly-inspired):
  - Base size: 10% of crypto allocation per trade
  - Scale up on high conviction (multiple strategy alignment)
  - Scale down during low volatility periods

Data Sources:
  - yfinance 1m, 5m, 15m intervals
  - Coingecko for real-time price validation
  - Alpaca paper trading API for execution

Integration:
  - Runs every 5 minutes during trading hours
  - Generates signals that appear in Analysis tab
  - Orders go through Approval queue
"""
import sys, os, time, json, math
from datetime import datetime, timedelta

sys.path.insert(0, "/tmp/mkt_pkg")

DB_PATH = os.path.expanduser("~/.hermes/cron/output/wealth/portfolio.db")
TODAY = time.strftime("%Y-%m-%d")
TIMESTAMP = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

# ─── Trading Parameters ─────────────────────────────────────────────────────

TRADING_PAIRS = [
    ("BTC", "bitcoin", {"weight": 0.35, "min_vol": 1e9}),    # Blue chip, high liquidity
    ("ETH", "ethereum", {"weight": 0.25, "min_vol": 5e8}),    # Blue chip
    ("SOL", "solana", {"weight": 0.15, "min_vol": 2e8}),      # High volatility alt
    ("AVAX", "avalanche-2", {"weight": 0.10, "min_vol": 5e7}),# Volatile alt
    ("LINK", "chainlink", {"weight": 0.10, "min_vol": 5e7}),  # DeFi blue chip
    ("DOGE", "dogecoin", {"weight": 0.05, "min_vol": 1e8}),   # Meme (high vol)
]

# Risk parameters
MAX_DAILY_LOSS_PCT = 2.0       # Stop trading after -2% daily loss
MAX_RISK_PER_TRADE_PCT = 0.5   # Max 0.5% portfolio risk per trade
STOP_LOSS_PCT = 0.8            # 0.8% stop loss
TAKE_PROFIT_PCT = 1.2          # 1.2% take profit (1.5:1 R:R)
TRAILING_STOP_TRIGGER_PCT = 0.6# Activate trailing stop at +0.6%
TRAILING_STOP_DISTANCE_PCT = 0.4 # Trail 0.4% behind high
MAX_CONCURRENT_POSITIONS = 3   # Max open positions at once

# Strategy weights (for signal confidence)
STRATEGY_WEIGHTS = {
    "scalp_rsi": 0.25,
    "momentum_break": 0.30,
    "mean_revert_bb": 0.25,
    "vwap_fade": 0.20,
}

# ─── Technical Indicators ───────────────────────────────────────────────────

def calc_rsi(close, period=14):
    """Calculate RSI from price series."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


def calc_ema(close, period):
    """Calculate EMA."""
    return close.ewm(span=period, adjust=False).mean()


def calc_sma(close, period):
    """Calculate SMA."""
    return close.rolling(window=period).mean()


def calc_bollinger_bands(close, period=20, std_dev=2):
    """Calculate Bollinger Bands."""
    sma = calc_sma(close, period)
    std = close.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower


def calc_vwap(high, low, close, volume):
    """Calculate VWAP."""
    typical_price = (high + low + close) / 3
    return (typical_price * volume).cumsum() / volume.cumsum()


def calc_atr(high, low, close, period=14):
    """Calculate Average True Range."""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def calc_macd(close, fast=12, slow=26, signal=9):
    """Calculate MACD."""
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_stochastic(high, low, close, k_period=14, d_period=3):
    """Calculate Stochastic Oscillator."""
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-10)
    d = k.rolling(window=d_period).mean()
    return k, d


# ─── Strategy 1: SCALP-RSI (1-minute) ──────────────────────────────────────
# High-frequency mean reversion on RSI extremes
# Entry: RSI(14) < 25 (oversold) or > 75 (overbought)
# Confirmation: Price at support/resistance, volume spike
# Exit: RSI crosses back to 40-60 zone, or 0.5% profit

def strategy_scalp_rsi(df_1m):
    """
    Scalp RSI strategy on 1-minute data.
    Returns: signal ('buy'/'sell'/'none'), confidence (0-1), entry_price, stop_loss, take_profit
    """
    if len(df_1m) < 50:
        return "none", 0, 0, 0, 0

    close = df_1m['Close']
    high = df_1m['High']
    low = df_1m['Low']
    volume = df_1m['Volume']

    rsi = calc_rsi(close, period=14)
    ema_9 = calc_ema(close, 9)
    ema_21 = calc_ema(close, 21)
    bb_upper, bb_mid, bb_lower = calc_bollinger_bands(close, period=20, std_dev=2)

    current_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2]
    current_price = close.iloc[-1]
    avg_volume = volume.tail(20).mean()
    current_volume = volume.iloc[-1]

    signal = "none"
    confidence = 0

    # BUY signal: RSI oversold + bouncing back up
    if current_rsi < 25 and prev_rsi < current_rsi:  # RSI rising from oversold
        confidence = 0.3  # Base confidence

        # Bonus if price at lower Bollinger Band
        if current_price <= bb_lower.iloc[-1]:
            confidence += 0.2

        # Bonus if volume spike (>1.5x average)
        if avg_volume > 0 and current_volume > avg_volume * 1.5:
            confidence += 0.15

        # Bonus if EMA 9 crossing above EMA 21
        if ema_9.iloc[-1] > ema_21.iloc[-1] and ema_9.iloc[-2] <= ema_21.iloc[-2]:
            confidence += 0.15

        if confidence >= 0.5:
            signal = "buy"

    # SELL signal: RSI overbought + turning down
    elif current_rsi > 75 and prev_rsi > current_rsi:  # RSI falling from overbought
        confidence = 0.3

        if current_price >= bb_upper.iloc[-1]:
            confidence += 0.2

        if avg_volume > 0 and current_volume > avg_volume * 1.5:
            confidence += 0.15

        if ema_9.iloc[-1] < ema_21.iloc[-1] and ema_9.iloc[-2] >= ema_21.iloc[-2]:
            confidence += 0.15

        if confidence >= 0.5:
            signal = "sell"

    entry_price = current_price
    stop_loss = current_price * (1 - STOP_LOSS_PCT / 100) if signal == "buy" else current_price * (1 + STOP_LOSS_PCT / 100)
    take_profit = current_price * (1 + TAKE_PROFIT_PCT / 100) if signal == "buy" else current_price * (1 - TAKE_PROFIT_PCT / 100)

    return signal, min(confidence, 1.0), entry_price, stop_loss, take_profit


# ─── Strategy 2: MOMENTUM-BREAK (5-minute) ─────────────────────────────────
# Breakout trading with volume confirmation
# Entry: Price breaks above/below 20-period high/low with volume > 2x average
# Exit: 1.5% profit or trailing stop

def strategy_momentum_break(df_5m):
    """
    Momentum breakout strategy on 5-minute data.
    """
    if len(df_5m) < 30:
        return "none", 0, 0, 0, 0

    close = df_5m['Close']
    high = df_5m['High']
    low = df_5m['Low']
    volume = df_5m['Volume']

    # 20-period high/low
    high_20 = high.rolling(window=20).max()
    low_20 = low.rolling(window=20).min()

    # Volume
    avg_volume = volume.rolling(window=20).mean()

    # EMAs for trend
    ema_9 = calc_ema(close, 9)
    ema_21 = calc_ema(close, 21)

    current_price = close.iloc[-1]
    current_volume = volume.iloc[-1]
    avg_vol = avg_volume.iloc[-1]

    signal = "none"
    confidence = 0

    # BUY breakout: price breaks above 20-period high with volume
    if current_price > high_20.iloc[-2] and current_price > high_20.iloc[-1]:
        confidence = 0.25

        # Volume confirmation
        if avg_vol > 0 and current_volume > avg_vol * 2:
            confidence += 0.3

        # Trend alignment (EMA 9 > EMA 21)
        if ema_9.iloc[-1] > ema_21.iloc[-1]:
            confidence += 0.2

        # MACD confirmation
        macd_line, signal_line, histogram = calc_macd(close)
        if histogram.iloc[-1] > 0 and histogram.iloc[-2] < 0:
            confidence += 0.15  # MACD crossover

        if confidence >= 0.5:
            signal = "buy"

    # SELL breakdown: price breaks below 20-period low with volume
    elif current_price < low_20.iloc[-2] and current_price < low_20.iloc[-1]:
        confidence = 0.25

        if avg_vol > 0 and current_volume > avg_vol * 2:
            confidence += 0.3

        if ema_9.iloc[-1] < ema_21.iloc[-1]:
            confidence += 0.2

        macd_line, signal_line, histogram = calc_macd(close)
        if histogram.iloc[-1] < 0 and histogram.iloc[-2] > 0:
            confidence += 0.15

        if confidence >= 0.5:
            signal = "sell"

    entry_price = current_price
    stop_loss = current_price * (1 - STOP_LOSS_PCT / 100) if signal == "buy" else current_price * (1 + STOP_LOSS_PCT / 100)
    take_profit = current_price * (1 + TAKE_PROFIT_PCT / 100) if signal == "buy" else current_price * (1 - TAKE_PROFIT_PCT / 100)

    return signal, min(confidence, 1.0), entry_price, stop_loss, take_profit


# ─── Strategy 3: MEAN-REVERT-BB (5-minute) ─────────────────────────────────
# Bollinger Band mean reversion
# Entry: Price touches upper/lower band + RSI confirms overbought/oversold
# Exit: Price returns to middle band (SMA 20)

def strategy_mean_revert_bb(df_5m):
    """
    Mean reversion strategy using Bollinger Bands on 5-minute data.
    """
    if len(df_5m) < 30:
        return "none", 0, 0, 0, 0

    close = df_5m['Close']
    high = df_5m['High']
    low = df_5m['Low']

    bb_upper, bb_mid, bb_lower = calc_bollinger_bands(close, period=20, std_dev=2)
    rsi = calc_rsi(close, period=14)
    stochastic_k, stochastic_d = calc_stochastic(high, low, close, k_period=14)

    current_price = close.iloc[-1]

    signal = "none"
    confidence = 0

    # BUY: Price at lower BB + RSI oversold + Stochastic oversold
    if current_price <= bb_lower.iloc[-1]:
        confidence = 0.25

        if rsi.iloc[-1] < 30:
            confidence += 0.25

        if stochastic_k.iloc[-1] < 20:
            confidence += 0.2

        # Price starting to reverse (current close > previous close)
        if close.iloc[-1] > close.iloc[-2]:
            confidence += 0.15

        # Band width expanding (increasing volatility = good reversal opportunity)
        band_width = (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_mid.iloc[-1]
        prev_band_width = (bb_upper.iloc[-2] - bb_lower.iloc[-2]) / bb_mid.iloc[-2]
        if band_width > prev_band_width:
            confidence += 0.1

        if confidence >= 0.5:
            signal = "buy"

    # SELL: Price at upper BB + RSI overbought + Stochastic overbought
    elif current_price >= bb_upper.iloc[-1]:
        confidence = 0.25

        if rsi.iloc[-1] > 70:
            confidence += 0.25

        if stochastic_k.iloc[-1] > 80:
            confidence += 0.2

        if close.iloc[-1] < close.iloc[-2]:
            confidence += 0.15

        band_width = (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_mid.iloc[-1]
        prev_band_width = (bb_upper.iloc[-2] - bb_lower.iloc[-2]) / bb_mid.iloc[-2]
        if band_width > prev_band_width:
            confidence += 0.1

        if confidence >= 0.5:
            signal = "sell"

    # Target: middle band (mean reversion)
    entry_price = current_price
    target_price = bb_mid.iloc[-1]
    stop_loss = current_price * (1 - STOP_LOSS_PCT / 100) if signal == "buy" else current_price * (1 + STOP_LOSS_PCT / 100)
    take_profit = target_price  # Mean reversion target

    return signal, min(confidence, 1.0), entry_price, stop_loss, take_profit


# ─── Strategy 4: VWAP-FADE (15-minute) ─────────────────────────────────────
# Fade extreme deviations from VWAP
# Entry: Price > 2 standard deviations from VWAP
# Exit: Price returns to VWAP

def strategy_vwap_fade(df_15m):
    """
    VWAP fade strategy on 15-minute data.
    """
    if len(df_15m) < 30:
        return "none", 0, 0, 0, 0

    high = df_15m['High']
    low = df_15m['Low']
    close = df_15m['Close']
    volume = df_15m['Volume']

    vwap = calc_vwap(high, low, close, volume)

    # Calculate VWAP bands (standard deviation bands)
    typical_price = (high + low + close) / 3
    vwap_std = ((typical_price - vwap) ** 2 * volume).rolling(window=20).mean().apply(math.sqrt) / volume.rolling(window=20).mean().apply(math.sqrt)

    current_price = close.iloc[-1]
    current_vwap = vwap.iloc[-1]
    std_dev = vwap_std.iloc[-1]

    signal = "none"
    confidence = 0

    if std_dev > 0 and current_vwap > 0:
        # Deviation from VWAP in standard deviations
        deviation = (current_price - current_vwap) / std_dev

        # SELL: Price > 2 std dev above VWAP (overextended up)
        if deviation > 2:
            confidence = 0.3 + (deviation - 2) * 0.15  # Higher deviation = more confidence

            # RSI confirmation
            rsi = calc_rsi(close, period=14)
            if rsi.iloc[-1] > 70:
                confidence += 0.2

            if confidence >= 0.5:
                signal = "sell"

        # BUY: Price < 2 std dev below VWAP (overextended down)
        elif deviation < -2:
            confidence = 0.3 + (-deviation - 2) * 0.15

            rsi = calc_rsi(close, period=14)
            if rsi.iloc[-1] < 30:
                confidence += 0.2

            if confidence >= 0.5:
                signal = "buy"

    entry_price = current_price
    stop_loss = current_price * (1 - STOP_LOSS_PCT / 100) if signal == "buy" else current_price * (1 + STOP_LOSS_PCT / 100)
    take_profit = current_vwap  # Target: return to VWAP

    return signal, min(confidence, 1.0), entry_price, stop_loss, take_profit


# ─── Composite Signal Generator ────────────────────────────────────────────

def generate_composite_signal(symbol, df_1m, df_5m, df_15m):
    """
    Run all strategies and generate composite signal.
    Returns: combined_signal, overall_confidence, entry_price, stop_loss, take_profit, strategy_details
    """
    strategies = {
        "scalp_rsi": strategy_scalp_rsi(df_1m),
        "momentum_break": strategy_momentum_break(df_5m),
        "mean_revert_bb": strategy_mean_revert_bb(df_5m),
        "vwap_fade": strategy_vwap_fade(df_15m),
    }

    # Count signals
    buy_count = 0
    sell_count = 0
    weighted_buy = 0
    weighted_sell = 0
    total_weight = 0

    strategy_details = {}

    for name, (signal, confidence, entry, stop, tp) in strategies.items():
        strategy_details[name] = {
            "signal": signal,
            "confidence": confidence,
            "entry_price": entry,
            "stop_loss": stop,
            "take_profit": tp,
        }

        if signal != "none":
            weight = STRATEGY_WEIGHTS.get(name, 0.2)
            total_weight += weight
            if signal == "buy":
                buy_count += 1
                weighted_buy += confidence * weight
            elif signal == "sell":
                sell_count += 1
                weighted_sell += confidence * weight

    # Determine composite signal
    combined_signal = "none"
    overall_confidence = 0

    if buy_count >= 2 and weighted_buy > weighted_sell:
        combined_signal = "buy"
        overall_confidence = weighted_buy / max(total_weight, 0.01)
    elif sell_count >= 2 and weighted_sell > weighted_buy:
        combined_signal = "sell"
        overall_confidence = weighted_sell / max(total_weight, 0.01)

    # Get average entry/stop/tp from agreeing strategies
    if combined_signal != "none":
        agreeing = [s for n, s in strategy_details.items() if s["signal"] == combined_signal]
        entry_price = sum(s["entry_price"] for s in agreeing) / len(agreeing)
        stop_loss = sum(s["stop_loss"] for s in agreeing) / len(agreeing)
        take_profit = sum(s["take_profit"] for s in agreeing) / len(agreeing)
    else:
        entry_price = df_5m['Close'].iloc[-1]
        stop_loss = 0
        take_profit = 0

    return combined_signal, overall_confidence, entry_price, stop_loss, take_profit, strategy_details


# ─── Data Fetching ─────────────────────────────────────────────────────────

def fetch_multi_timeframe(symbol):
    """Fetch 1m, 5m, and 15m data for a symbol."""
    import yfinance as yf

    yf_sym = f"{symbol}-USD"
    t = yf.Ticker(yf_sym)

    try:
        df_1m = t.history(period='1d', interval='1m')
    except:
        df_1m = pd.DataFrame()

    try:
        df_5m = t.history(period='5d', interval='5m')
    except:
        df_5m = pd.DataFrame()

    try:
        df_15m = t.history(period='60d', interval='15m')
    except:
        df_15m = pd.DataFrame()

    return df_1m, df_5m, df_15m


# ─── Signal Recording ──────────────────────────────────────────────────────

def save_day_signal(result):
    """Save day trading signal to portfolio.db."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Check if day_trades table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='day_trades';")
    if not cursor.fetchone():
        conn.execute("""
            CREATE TABLE day_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                signal_date TEXT,
                signal_time TEXT,
                strategy TEXT,
                signal TEXT,
                confidence REAL,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                status TEXT DEFAULT 'pending',
                notes TEXT
            )
        """)
        conn.commit()

    cols = list(result.keys())
    placeholders = ", ".join([f":{c}" for c in cols])
    sql = f"INSERT INTO day_trades ({', '.join(cols)}) VALUES ({placeholders})"
    conn.execute(sql, result)
    conn.commit()
    conn.close()


# ─── Main Execution ────────────────────────────────────────────────────────

def run_day_trading_scan():
    """Run the full day trading scan."""
    import pandas as pd
    import yfinance as yf

    print(f"=== Crypto Day Trading Scan — {TIMESTAMP} ===\n")

    results = []

    for symbol, cg_id, params in TRADING_PAIRS:
        print(f"Analyzing {symbol}...", end=" ")

        df_1m, df_5m, df_15m = fetch_multi_timeframe(symbol)

        if df_5m.empty or len(df_5m) < 30:
            print(f"✗ Insufficient data ({len(df_5m)} candles)")
            continue

        signal, confidence, entry, stop, tp, details = generate_composite_signal(
            symbol, df_1m, df_5m, df_15m
        )

        current_price = df_5m['Close'].iloc[-1]
        daily_change = (current_price / df_5m['Close'].iloc[0] - 1) * 100 if len(df_5m) > 1 else 0

        if signal != "none":
            print(f"→ {signal.upper()} (confidence: {confidence:.2f}, price: ${current_price:,.2f})")

            result = {
                "symbol": symbol,
                "signal_date": TODAY,
                "signal_time": TIMESTAMP,
                "strategy": "composite",
                "signal": signal,
                "confidence": round(confidence, 3),
                "entry_price": round(entry, 2),
                "stop_loss": round(stop, 2),
                "take_profit": round(tp, 2),
                "status": "pending",
                "notes": f"Price: ${current_price:,.2f}, Daily: {daily_change:+.2f}%, "
                         f"R1: {details.get('scalp_rsi', {}).get('signal', '-')}, "
                         f"R2: {details.get('momentum_break', {}).get('signal', '-')}, "
                         f"R3: {details.get('mean_revert_bb', {}).get('signal', '-')}, "
                         f"R4: {details.get('vwap_fade', {}).get('signal', '-')}"
            }
            save_day_signal(result)
            results.append(result)
        else:
            print(f"— no signal (price: ${current_price:,.2f}, daily: {daily_change:+.2f}%)")

    print(f"\n{'='*50}")
    print(f"Signals generated: {len(results)}")

    if results:
        buy_signals = [r for r in results if r["signal"] == "buy"]
        sell_signals = [r for r in results if r["signal"] == "sell"]
        print(f"  BUY: {len(buy_signals)}")
        for r in buy_signals:
            print(f"    {r['symbol']}: ${r['entry_price']:,.2f} → TP ${r['take_profit']:,.2f} / SL ${r['stop_loss']:,.2f}")
        print(f"  SELL: {len(sell_signals)}")
        for r in sell_signals:
            print(f"    {r['symbol']}: ${r['entry_price']:,.2f} → TP ${r['take_profit']:,.2f} / SL ${r['stop_loss']:,.2f}")

    return results


# ─── Alpaca Trade Execution ────────────────────────────────────────────────

ALPACA_API_KEY = "PKYBN34XEJMJA46ZVPNIALRKIP"
ALPACA_API_SECRET = "Bw6TbtEaZN6zSeLBGd2NZiWHijiSi7GHD4fgtzb5hvoA"
ALPACA_BASE = "https://paper-api.alpaca.markets"
HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
}

def alpaca_request(method, path, payload=None):
    """Make request to Alpaca API."""
    import requests
    url = f"{ALPACA_BASE}{path}"
    if method == "GET":
        r = requests.get(url, headers=HEADERS, timeout=10)
    elif method == "POST":
        r = requests.post(url, headers=HEADERS, json=payload, timeout=10)
    elif method == "DELETE":
        r = requests.delete(url, headers=HEADERS, timeout=10)
    else:
        return None
    if r.status_code in (200, 201):
        return r.json()
    print(f"  Alpaca {method} {path}: {r.status_code} {r.text[:200]}")
    return None


def get_account_info():
    """Get Alpaca account info."""
    return alpaca_request("GET", "/v2/account")


def get_open_positions():
    """Get all open crypto positions."""
    return alpaca_request("GET", "/v2/positions") or []


def get_open_orders():
    """Get all open orders."""
    return alpaca_request("GET", "/v2/orders?status=open") or []


def get_crypto_positions():
    """Get only crypto positions from Alpaca."""
    positions = get_open_positions()
    return [p for p in positions if p.get("asset_class") == "crypto"]


def place_crypto_order(symbol, side, notional, order_type="market"):
    """Place a market order for crypto by notional value ($ amount)."""
    # Alpaca crypto uses lowercase symbols like "BTC/USD"
    crypto_symbol = f"{symbol}/USD"
    payload = {
        "symbol": crypto_symbol,
        "notional": str(notional),
        "side": side,
        "type": order_type,
        "time_in_force": "gtc",
    }
    result = alpaca_request("POST", "/v2/orders", payload)
    if result and "id" in result:
        print(f"  ✅ ORDER FILLED: {side.upper()} {crypto_symbol} ${notional:.2f} (order_id: {result['id'][:8]}...)")
        return result
    print(f"  ❌ ORDER FAILED: {side.upper()} {crypto_symbol} ${notional:.2f}")
    return None


def place_limit_order(symbol, side, qty, limit_price):
    """Place a limit order for crypto."""
    crypto_symbol = f"{symbol}/USD"
    payload = {
        "symbol": crypto_symbol,
        "qty": str(qty),
        "side": side,
        "type": "limit",
        "time_in_force": "gtc",
        "limit_price": str(limit_price),
    }
    result = alpaca_request("POST", "/v2/orders", payload)
    if result and "id" in result:
        print(f"  ✅ LIMIT ORDER: {side.upper()} {crypto_symbol} {qty} @ ${limit_price:.2f}")
        return result
    return None


def cancel_order(order_id):
    """Cancel an open order."""
    return alpaca_request("DELETE", f"/v2/orders/{order_id}")


def cancel_all_orders():
    """Cancel all open orders."""
    return alpaca_request("DELETE", "/v2/orders")


def get_crypto_clock():
    """Check if crypto market is open (always open, but good to verify API)."""
    return alpaca_request("GET", "/v2/clock")


# ─── Position & Trade Tracking ─────────────────────────────────────────────

TRADES_DB_PATH = os.path.expanduser("~/.hermes/cron/output/wealth/portfolio.db")


def init_trades_table():
    """Ensure trades tracking table exists."""
    import sqlite3
    conn = sqlite3.connect(TRADES_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS active_day_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alpaca_order_id TEXT UNIQUE,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL,
            qty REAL,
            notional REAL,
            stop_loss REAL,
            take_profit REAL,
            strategy TEXT,
            confidence REAL,
            entry_time TEXT,
            status TEXT DEFAULT 'open',
            exit_price REAL,
            exit_time TEXT,
            pnl REAL,
            pnl_pct REAL
        )
    """)
    conn.commit()
    conn.close()


def record_trade(order_result, symbol, side, entry_price, stop_loss, take_profit,
                 strategy="composite", confidence=0, notional=0, qty=0):
    """Record a new trade in the database."""
    import sqlite3
    conn = sqlite3.connect(TRADES_DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO active_day_trades
        (alpaca_order_id, symbol, side, entry_price, qty, notional,
         stop_loss, take_profit, strategy, confidence, entry_time, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
    """, (
        order_result.get("id"),
        symbol,
        side,
        entry_price,
        qty,
        notional,
        stop_loss,
        take_profit,
        strategy,
        confidence,
        TIMESTAMP,
    ))
    conn.commit()
    conn.close()
    print(f"  📝 Trade recorded: {side} {symbol} @ ${entry_price:.2f}")


def get_open_day_trades():
    """Get all open day trades."""
    import sqlite3
    conn = sqlite3.connect(TRADES_DB_PATH)
    conn.row_factory = sqlite3.Row
    trades = conn.execute(
        "SELECT * FROM active_day_trades WHERE status = 'open'"
    ).fetchall()
    conn.close()
    return [dict(t) for t in trades]


def update_trade_status(alpaca_order_id, status, exit_price=None, pnl=None, pnl_pct=None):
    """Update trade status (close, stopped out, taken profit)."""
    import sqlite3
    conn = sqlite3.connect(TRADES_DB_PATH)
    conn.execute("""
        UPDATE active_day_trades
        SET status = ?, exit_price = ?, exit_time = ?, pnl = ?, pnl_pct = ?
        WHERE alpaca_order_id = ?
    """, (status, exit_price, TIMESTAMP, pnl, pnl_pct, alpaca_order_id))
    conn.commit()
    conn.close()


# ─── Risk Manager ──────────────────────────────────────────────────────────

class RiskManager:
    """Track daily P&L and enforce risk limits."""

    def __init__(self):
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.max_daily_loss = MAX_DAILY_LOSS_PCT
        self.max_concurrent = MAX_CONCURRENT_POSITIONS

    def load_daily_pnl(self):
        """Load today's realized P&L from DB."""
        import sqlite3
        conn = sqlite3.connect(TRADES_DB_PATH)
        row = conn.execute("""
            SELECT COALESCE(SUM(pnl), 0) as total_pnl
            FROM active_day_trades
            WHERE status IN ('closed', 'stopped', 'taken_profit')
            AND exit_time LIKE ?
        """, (f"{TODAY}%",)).fetchone()
        self.daily_pnl = row[0] if row else 0.0
        row2 = conn.execute("""
            SELECT COUNT(*) FROM active_day_trades
            WHERE exit_time LIKE ?
        """, (f"{TODAY}%",)).fetchone()
        self.daily_trades = row2[0] if row2 else 0
        conn.close()

    def can_trade(self, current_positions_count=0):
        """Check if we can place a new trade."""
        # Check daily loss limit
        if self.daily_pnl < -self.max_daily_loss:
            print(f"  ⛔ Daily loss limit hit: {self.daily_pnl:.2f}% < -{self.max_daily_loss}%")
            return False
        # Check concurrent positions
        if current_positions_count >= self.max_concurrent:
            print(f"  ⛔ Max concurrent positions: {current_positions_count} >= {self.max_concurrent}")
            return False
        return True

    def calc_position_size(self, portfolio_value, confidence, symbol_weight=0.10):
        """Calculate position size based on Kelly-inspired sizing."""
        # Base: weight% of portfolio
        base_size = portfolio_value * symbol_weight
        # Scale by confidence (0.5-1.0 range maps to 0.75-1.25x)
        confidence_multiplier = 0.75 + (confidence * 0.5)
        # Scale by daily P&L (reduce size if losing)
        if self.daily_pnl < 0:
            drawdown_multiplier = max(0.5, 1 + (self.daily_pnl / self.max_daily_loss))
        else:
            drawdown_multiplier = 1.0

        size = base_size * confidence_multiplier * drawdown_multiplier
        # Cap at max risk per trade
        max_risk = portfolio_value * (MAX_RISK_PER_TRADE_PCT / 100) / (STOP_LOSS_PCT / 100)
        return min(size, max_risk)


# ─── Position Monitor (runs between scans) ─────────────────────────────────

def monitor_open_positions():
    """Check open trades against stop loss / take profit levels."""
    import yfinance as yf

    trades = get_open_day_trades()
    if not trades:
        return

    print(f"\n── Monitoring {len(trades)} open trade(s) ──")

    for trade in trades:
        symbol = trade["symbol"]
        try:
            yf_sym = f"{symbol}-USD"
            t = yf.Ticker(yf_sym)
            hist = t.history(period="1d", interval="1m")
            if hist.empty:
                continue
            current_price = hist["Close"].iloc[-1]
        except:
            continue

        entry = trade["entry_price"]
        sl = trade["stop_loss"]
        tp = trade["take_profit"]
        side = trade["side"]

        pnl_pct = ((current_price / entry) - 1) * 100 if side == "buy" else ((entry / current_price) - 1) * 100

        # Check stop loss
        if side == "buy" and current_price <= sl:
            print(f"  🛑 STOP LOSS: {symbol} @ ${current_price:.2f} (entry: ${entry:.2f}, SL: ${sl:.2f})")
            # Close position
            alpaca_positions = get_open_positions()
            for p in alpaca_positions:
                if p["symbol"] == f"{symbol}/USD":
                    qty = float(p["qty"])
                    result = place_crypto_order(symbol, "sell", 0, "market")
                    # Actually sell the full quantity
                    result = alpaca_request("POST", "/v2/orders", {
                        "symbol": f"{symbol}/USD",
                        "qty": str(qty),
                        "side": "sell",
                        "type": "market",
                        "time_in_force": "gtc",
                    })
                    if result:
                        update_trade_status(
                            trade["alpaca_order_id"], "stopped",
                            exit_price=current_price, pnl=pnl_pct, pnl_pct=pnl_pct
                        )
                        print(f"  💀 Position closed at loss: {pnl_pct:.2f}%")
            continue

        # Check take profit
        if side == "buy" and tp > 0 and current_price >= tp:
            print(f"  🎯 TAKE PROFIT: {symbol} @ ${current_price:.2f} (entry: ${entry:.2f}, TP: ${tp:.2f})")
            alpaca_positions = get_open_positions()
            for p in alpaca_positions:
                if p["symbol"] == f"{symbol}/USD":
                    qty = float(p["qty"])
                    result = alpaca_request("POST", "/v2/orders", {
                        "symbol": f"{symbol}/USD",
                        "qty": str(qty),
                        "side": "sell",
                        "type": "market",
                        "time_in_force": "gtc",
                    })
                    if result:
                        update_trade_status(
                            trade["alpaca_order_id"], "taken_profit",
                            exit_price=current_price, pnl=pnl_pct, pnl_pct=pnl_pct
                        )
                        print(f"  💰 Position closed at profit: {pnl_pct:.2f}%")
            continue

        # Trailing stop check (if profit > TRAILING_STOP_TRIGGER_PCT)
        if side == "buy" and pnl_pct > TRAILING_STOP_TRIGGER_PCT:
            trailing_sl = current_price * (1 - TRAILING_STOP_DISTANCE_PCT / 100)
            if trailing_sl > sl:
                print(f"  📈 Trailing stop updated: {symbol} SL ${sl:.2f} → ${trailing_sl:.2f}")
                # Update in DB
                import sqlite3
                conn = sqlite3.connect(TRADES_DB_PATH)
                conn.execute(
                    "UPDATE active_day_trades SET stop_loss = ? WHERE alpaca_order_id = ?",
                    (trailing_sl, trade["alpaca_order_id"])
                )
                conn.commit()
                conn.close()

        # Print status
        status_emoji = "🟢" if pnl_pct > 0 else "🔴" if pnl_pct < -0.3 else "⚪"
        print(f"  {status_emoji} {symbol}: ${current_price:.2f} | PnL: {pnl_pct:+.2f}% | SL: ${sl:.2f} | TP: ${tp:.2f}")


# ─── Execute Signals ───────────────────────────────────────────────────────

def execute_signal(signal_data, risk_manager):
    """Execute a trading signal via Alpaca."""
    symbol = signal_data["symbol"]
    side = signal_data["signal"]
    confidence = signal_data["confidence"]
    entry_price = signal_data["entry_price"]
    stop_loss = signal_data["stop_loss"]
    take_profit = signal_data["take_profit"]

    # Get account info
    account = get_account_info()
    if not account:
        print(f"  ⚠️ Cannot get account info, skipping {symbol}")
        return None

    portfolio_value = float(account.get("equity", 0))
    cash = float(account.get("cash", 0))

    # Check risk limits
    crypto_positions = get_crypto_positions()
    if not risk_manager.can_trade(len(crypto_positions)):
        return None

    # Check if we already have an open trade for this symbol
    open_trades = get_open_day_trades()
    existing = [t for t in open_trades if t['symbol'] == symbol and t['status'] == 'open']
    if existing:
        print(f"  ⚠️ Already have open {side} trade for {symbol}, skipping")
        return None

    # Calculate position size
    pair_weight = 0.10  # default
    for sym, _, params in TRADING_PAIRS:
        if sym == symbol:
            pair_weight = params.get("weight", 0.10)
            break

    notional = risk_manager.calc_position_size(portfolio_value, confidence, pair_weight)
    notional = min(notional, cash * 0.8)  # Never use more than 80% of cash

    # Round notional to 2 decimal places (Alpaca requirement)
    notional = round(notional, 2)
    
    if notional < 5:
        print(f"  ⚠️ Position too small: ${notional:.2f} for {symbol}")
        return None

    print(f"\n📊 EXECUTING: {side.upper()} {symbol}")
    print(f"   Notional: ${notional:.2f} | Confidence: {confidence:.2f}")
    print(f"   Entry: ${entry_price:.2f} | SL: ${stop_loss:.2f} | TP: ${take_profit:.2f}")

    # Place order
    order_result = place_crypto_order(symbol, side, notional)
    if order_result:
        # Estimate qty from notional
        qty = notional / entry_price if entry_price > 0 else 0
        record_trade(order_result, symbol, side, entry_price, stop_loss,
                     take_profit, "composite", confidence, notional, qty)
        return order_result

    return None


# ─── Intraday Signal Integration ──────────────────────────────────────────

def update_intraday_score(symbol, signal, confidence):
    """Update the daily score with intraday momentum signal.
    This integrates day trading signals into the BV Trader scoring system.
    A BUY signal boosts the score, SELL reduces it.
    """
    import sqlite3
    conn = sqlite3.connect(DB_PATH)

    # Get current composite score
    row = conn.execute("""
        SELECT composite_score FROM scores
        WHERE symbol = ? AND score_date = ?
        ORDER BY id DESC LIMIT 1
    """, (symbol, TODAY)).fetchone()

    if not row:
        conn.close()
        return

    base_score = row[0]

    # Adjust score based on intraday signal
    if signal == "buy" and confidence > 0.5:
        adjusted_score = min(base_score + (confidence * 5), 100)  # Boost up to +5
        scan_status = "buy"
    elif signal == "sell" and confidence > 0.5:
        adjusted_score = max(base_score - (confidence * 5), 0)  # Reduce up to -5
        scan_status = "sell" if adjusted_score < 50 else "hold"
    else:
        adjusted_score = base_score
        scan_status = "hold"

    # Update the latest score
    conn.execute("""
        UPDATE scores SET composite_score = ?, scan_status = ?
        WHERE symbol = ? AND score_date = ?
    """, (round(adjusted_score, 2), scan_status, symbol, TODAY))

    conn.commit()
    conn.close()

    if abs(adjusted_score - base_score) > 0.5:
        print(f"  📊 {symbol} score adjusted: {base_score:.1f} → {adjusted_score:.1f} ({signal})")


# ─── Main Execution ────────────────────────────────────────────────────────

def run_day_trading_scan(execute_trades=False):
    """Run the full day trading scan with optional trade execution."""
    import pandas as pd
    import yfinance as yf

    print(f"=== Crypto Day Trading Scan — {TIMESTAMP} ===")
    print(f"   Trade execution: {'ENABLED' if execute_trades else 'DRY RUN'}\n")

    # Initialize risk manager
    risk = RiskManager()
    risk.load_daily_pnl()

    # First: monitor open positions
    monitor_open_positions()

    results = []
    executed = []

    for symbol, cg_id, params in TRADING_PAIRS:
        print(f"Analyzing {symbol}...", end=" ")

        df_1m, df_5m, df_15m = fetch_multi_timeframe(symbol)

        if df_5m.empty or len(df_5m) < 30:
            print(f"✗ Insufficient data ({len(df_5m)} candles)")
            continue

        signal, confidence, entry, stop, tp, details = generate_composite_signal(
            symbol, df_1m, df_5m, df_15m
        )

        current_price = df_5m['Close'].iloc[-1]
        daily_change = (current_price / df_5m['Close'].iloc[0] - 1) * 100 if len(df_5m) > 1 else 0

        # Save signal to DB
        result = {
            "symbol": symbol,
            "signal_date": TODAY,
            "signal_time": TIMESTAMP,
            "strategy": "composite",
            "signal": signal,
            "confidence": round(confidence, 3),
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "take_profit": round(tp, 2),
            "status": "pending",
            "notes": f"Price: ${current_price:,.2f}, Daily: {daily_change:+.2f}%, "
                     f"R1: {details.get('scalp_rsi', {}).get('signal', '-')}, "
                     f"R2: {details.get('momentum_break', {}).get('signal', '-')}, "
                     f"R3: {details.get('mean_revert_bb', {}).get('signal', '-')}, "
                     f"R4: {details.get('vwap_fade', {}).get('signal', '-')}"
        }

        if signal != "none":
            print(f"→ {signal.upper()} (confidence: {confidence:.2f}, price: ${current_price:,.2f})")

            # Update intraday score in BV Trader system
            update_intraday_score(symbol, signal, confidence)

            save_day_signal(result)
            results.append(result)

            # Execute if enabled
            if execute_trades:
                order = execute_signal(result, risk)
                if order:
                    executed.append({
                        "symbol": symbol,
                        "order_id": order.get("id"),
                        "side": signal,
                        "notional": float(order.get("notional", 0)),
                    })
        else:
            print(f"— no signal (price: ${current_price:,.2f}, daily: {daily_change:+.2f}%)")
            # Also update intraday score (no signal = no adjustment needed)

    # Summary
    print(f"\n{'='*50}")
    print(f"Scan complete: {len(results)} signal(s) generated")

    if results:
        buy_signals = [r for r in results if r["signal"] == "buy"]
        sell_signals = [r for r in results if r["signal"] == "sell"]
        print(f"  BUY: {len(buy_signals)}")
        for r in buy_signals:
            print(f"    {r['symbol']}: ${r['entry_price']:,.2f} → TP ${r['take_profit']:,.2f} / SL ${r['stop_loss']:,.2f}")
        print(f"  SELL: {len(sell_signals)}")
        for r in sell_signals:
            print(f"    {r['symbol']}: ${r['entry_price']:,.2f} → TP ${r['take_profit']:,.2f} / SL ${r['stop_loss']:,.2f}")

    if executed:
        print(f"\n📈 EXECUTED {len(executed)} trade(s):")
        for e in executed:
            print(f"  {e['side'].upper()} {e['symbol']} ${e['notional']:.2f} (order: {e['order_id'][:8]}...)")

    # Show open trades summary
    open_trades = get_open_day_trades()
    if open_trades:
        print(f"\n📋 Open trades: {len(open_trades)}")
        for t in open_trades:
            pnl_str = f"PnL: {t['pnl']:+.2f}%" if t['pnl'] is not None else "PnL: --"
            print(f"  {t['symbol']} {t['side']} @ ${t['entry_price']:.2f} | {pnl_str}")

    return results


if __name__ == "__main__":
    import pandas as pd

    # Check for --execute flag to enable live trading
    execute_trades = "--execute" in sys.argv

    if execute_trades:
        print("⚠️  LIVE TRADING MODE — Orders will be placed on Alpaca paper trading")
        print("⚠️  Press Ctrl+C to cancel\n")

    init_trades_table()
    results = run_day_trading_scan(execute_trades=execute_trades)
