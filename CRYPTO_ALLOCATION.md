# BV Trader — Crypto Allocation Strategy (25% Portfolio)

## Overview
Allocate 25% of portfolio to crypto for 24/7 trading opportunity.
Current portfolio: ~$100K → **$25K crypto allocation**

## Position Sizing (Tiered Risk Model)

### Tier 1: Blue Chip (40% of crypto = $10K)
- **BTC** (60% of tier = $6K): Store of value, ETF approved, institutional grade
- **ETH** (40% of tier = $4K): Smart contract platform, ETF approved, DeFi backbone

### Tier 2: Core Altcoins (35% of crypto = $8.75K)
- **SOL** (30% = $2.6K): High-performance L1, growing ecosystem
- **LINK** (20% = $1.75K): Oracle network, critical infrastructure
- **AVAX** (15% = $1.3K): Subnet platform, institutional partnerships
- **DOT** (15% = $1.3K): Parachain network, interoperability
- **ADA** (10% = $0.875K): Research-driven, strong community
- **ARB** (10% = $0.875K): Leading L2, Ethereum scaling

### Tier 3: Narrative Plays (25% of crypto = $6.25K)
- **DeFi**: AAVE, UNI, CRV, LDO (4 tokens, ~$1.5K each)
- **AI**: RENDER, GRT (2 tokens, ~$1.5K each)
- **RWA**: ONDO, PAXG (2 tokens, ~$1.5K each)
- **Meme**: DOGE (1 token, ~$1.25K)

## Entry/Exit Rules

### Entry Criteria
- Composite score ≥ 60 (BUY signal)
- For Tier 1: DCA over 3-5 days regardless of score
- For Tier 2/3: Wait for BUY signal + confirm with Rule 5 (quantitative) ≥ 50

### Exit Criteria
- Composite score < 40 (SELL signal)
- Stop loss: -15% from entry for Tier 2/3, -10% for Tier 1
- Take profit: +50% for Tier 3, +30% for Tier 2, +20% for Tier 1

### Rebalancing
- Weekly: Check scores, rebalance if any position >15% of crypto allocation
- Monthly: Full review, adjust tier allocations based on market cycle
- Trigger: BTC halving cycle phase change → shift allocation between tiers

## Risk Management
- Max single position: 25% of crypto allocation ($6.25K)
- Max sector exposure: 40% of crypto allocation ($10K)
- Stablecoins count as cash, not crypto allocation
- Meme coins max 10% of crypto allocation ($2.5K)

## Scoring Thresholds (Crypto-Specific)
- BUY: composite ≥ 60 (lower than stocks due to higher volatility)
- HOLD: 40-59
- AVOID/SELL: < 40

## Data Sources
- **yfinance (-USD suffix)**: Price history, moving averages, volume
- **Coingecko API (free)**: Market cap, supply, ATH, TVL, dev/community stats
- **DeFiLlama API (free)**: TVL for DeFi protocols

## Integration with Existing System
- `crypto_scoring.py` runs alongside `portfolio_manager.py`
- Scores saved to same `scores` table with `asset_type='crypto'`
- Dashboard shows crypto positions separately from stocks
- Library endpoint includes crypto with sector/industry/marketCap

## 24/7 Trading Workflow
1. Market scan runs hourly (10am-3pm weekdays) for stocks
2. Crypto scan runs every 4 hours (6am, 10am, 2pm, 6pm, 10pm, 2am)
3. Signals generated automatically, appear in Analysis tab
4. Manual approval required before execution
5. Alpaca supports 24/7 crypto trading (paper trading mode)

## Monitoring
- Track crypto allocation % daily
- Alert if crypto > 30% or < 20% of total portfolio
- Weekly report on crypto performance vs stocks
