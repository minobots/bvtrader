#!/usr/local/bin/python3
"""
Portfolio Management System — Core Database Schema
SQLite: stocks, etfs, scores, signals, positions, orders
"""
import sqlite3, os
from datetime import datetime, date

DB_PATH = os.path.expanduser("~/.hermes/cron/output/wealth/portfolio.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    UNIQUE NOT NULL,
    name            TEXT,
    asset_type      TEXT    DEFAULT 'stock',   -- stock / etf / index
    sector          TEXT,
    industry        TEXT,
    market_cap      REAL,
    market_cap_class TEXT,  -- mega / large / mid / small / micro
    exchange        TEXT,
    country         TEXT    DEFAULT 'US',
    fifty_two_high  REAL,
    fifty_two_low   REAL,
    added_date      TEXT,
    source          TEXT    DEFAULT 'yahoo',   -- how we found it
    notes           TEXT,
    flagged         INTEGER DEFAULT 0,
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS etf_track (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    UNIQUE NOT NULL,
    name            TEXT,
    category        TEXT,
    focus           TEXT,    -- large-cap, tech, dividend, etc.
    expense_ratio   REAL,
    aum             REAL,
    avg_volume      INTEGER,
    holdings_count  INTEGER,
    top_holdings    TEXT,    -- JSON array
    added_date      TEXT,
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_quotes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,
    open_           REAL,
    high            REAL,
    low              REAL,
    close           REAL,
    adj_close       REAL,
    volume          INTEGER,
    close_pct_chg   REAL,
    fifty_two_high  REAL,
    fifty_two_low   REAL,
    sma_20          REAL,
    sma_50          REAL,
    sma_200         REAL,
    rsi_14          REAL,
    volume_ratio    REAL,   -- today's vol / 20d avg vol
    UNIQUE(symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    UNIQUE NOT NULL,
    pe_ratio        REAL,
    forward_pe      REAL,
    peg_ratio       REAL,
    pb_ratio        REAL,
    ps_ratio        REAL,
    pcfratio        REAL,
    eps_ttm         REAL,
    eps_forward     REAL,
    eps_growth_5y   REAL,
    div_yield       REAL,
    payout_ratio    REAL,
    beta            REAL,
    debt_to_equity  REAL,
    current_ratio   REAL,
    quick_ratio     REAL,
    Altman_Z        REAL,
    roe             REAL,
    roa             REAL,
    roc             REAL,
    rev_growth_1y   REAL,
    profit_margin   REAL,
    operating_margin REAL,
    gross_margin    REAL,
    free_cash_flow  REAL,
    operating_cash_flow REAL,
    total_cash      REAL,
    total_debt      REAL,
    shares_out      REAL,
    rev_ttm         REAL,
    earnings_date   TEXT,
    fetched_date    TEXT,
    FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);

CREATE TABLE IF NOT EXISTS scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    score_date      TEXT    NOT NULL,
    tier            TEXT    DEFAULT 'quick',  -- quick / deep
    -- Rule 1: Fundamental (0-100)
    f_earning_quality REAL,
    f_growth_rate      REAL,
    f_balance_sheet    REAL,
    f_market_position  REAL,
    f_profitability    REAL,
    f_rule1总分         REAL,
    -- Rule 2: Opportunistic (0-100)
    o_pullback_depth   REAL,
    o_mean_reversion   REAL,
    o_sector_recovery  REAL,
    o_sentiment_turn   REAL,
    o_value_distance   REAL,
    o_rule2总分        REAL,
    -- Rule 3: Market Event (0-100)
    m_sector_rotation  REAL,
    m_macro_tailwind   REAL,
    m_policy_benefit   REAL,
    m_feed_flows      REAL,
    m_market_cap      REAL,
    m_rule3总分        REAL,
    -- Rule 4: Politically Aligned (0-100)
    p_policy_exposure REAL,
    p_regulatory_risk REAL,
    p_subsidy_benefit  REAL,
    p_trade_exposure  REAL,
    p_geopolitical    REAL,
    p_rule4总分        REAL,
    -- Rule 5: Quantitative (0-100)
    q_trend_score      REAL,
    q_momentum         REAL,
    q_low_volatility   REAL,
    q_relative_strength REAL,
    q_vol_profile      REAL,
    q_rule5总分        REAL,
    -- Composite
    composite_score    REAL,
    composite_rank     INTEGER,
    scan_status        TEXT,   -- buy / hold / avoid / watch
    created_at         TEXT    DEFAULT (datetime('now')),
    UNIQUE(symbol, score_date, tier)
);

CREATE TABLE IF NOT EXISTS portfolio (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    UNIQUE NOT NULL,
    shares          REAL,
    avg_cost        REAL,
    current_price   REAL,
    market_value    REAL,
    unrealized_pl   REAL,
    unrealized_plpct REAL,
    sector          TEXT,
    position_size   REAL,   -- % of portfolio
    conviction_level INTEGER DEFAULT 0,  -- 1-5, Alex's priority
    rule1_score     REAL,
    rule2_score     REAL,
    rule3_score     REAL,
    rule4_score     REAL,
    rule5_score     REAL,
    composite_score REAL,
    updated_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    signal_date      TEXT    NOT NULL,
    signal_type      TEXT,   -- buy / sell / hold / upgrade / downgrade
    trigger_rule    TEXT,   -- which rule triggered
    trigger_detail  TEXT,
    score_before    REAL,
    score_after     REAL,
    price_at_signal REAL,
    target_price    REAL,
    stop_loss       REAL,
    conviction      TEXT,   -- high / medium / low
    status          TEXT    DEFAULT 'active',  -- active / triggered / expired / cancelled
    action_taken    TEXT,   -- order placed / approved / skipped
    alpaca_order_id TEXT,
    notes           TEXT,
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS library_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    UNIQUE NOT NULL,
    priority        INTEGER DEFAULT 5,   -- 1=highest
    tier            TEXT    DEFAULT 'quick',
    status          TEXT    DEFAULT 'pending',  -- pending / scanning / scored / failed
    added_date      TEXT,
    scheduled_date  TEXT,
    scanned_date    TEXT,
    attempts        INTEGER DEFAULT 0,
    score_id        INTEGER REFERENCES scores(id),
    notes           TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders_tracking (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alpaca_order_id TEXT    UNIQUE NOT NULL,
    symbol          TEXT,
    side            TEXT,
    qty             REAL,
    order_type      TEXT,
    limit_price     REAL,
    filled_qty      REAL,
    filled_price    REAL,
    status          TEXT,
    created_at      TEXT,
    filled_at       TEXT,
    strategy_rule   TEXT,
    trigger_signal_id INTEGER REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS scan_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date       TEXT    NOT NULL,
    scan_type       TEXT,   -- full / portfolio_only / signal_check
    stocks_scanned  INTEGER,
    new_signals     INTEGER,
    orders_placed   INTEGER,
    duration_secs   REAL,
    status          TEXT,
    errors          TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_quotes_sym_date ON daily_quotes(symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_scores_sym_date ON scores(symbol, score_date);
CREATE INDEX IF NOT EXISTS idx_signals_sym ON signals(symbol, signal_date);
CREATE INDEX IF NOT EXISTS idx_queue_status ON library_queue(status, priority);
"""

def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"[{time_str()}] DB initialized at {DB_PATH}")

def time_str():
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

if __name__ == "__main__":
    import time as _time
    init_db()