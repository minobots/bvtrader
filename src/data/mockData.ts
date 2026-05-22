import type { Position, Order, Recommendation, PortfolioSummary, WatchlistItem } from '../types';

export const mockPortfolio: PortfolioSummary = {
  totalValue: 52480.22,
  cash: 8420.00,
  equity: 44060.22,
  dayChange: 312.45,
  dayChangePct: 0.60,
};

export const mockPositions: Position[] = [
  { symbol: 'AAPL', name: 'Apple Inc.', qty: 50, avgEntryPrice: 178.20, currentPrice: 182.50, marketValue: 9125.00, unrealizedPL: 215.00, unrealizedPLPct: 2.42, sector: 'Technology' },
  { symbol: 'MSFT', name: 'Microsoft Corp', qty: 30, avgEntryPrice: 415.00, currentPrice: 422.80, marketValue: 12684.00, unrealizedPL: 234.00, unrealizedPLPct: 1.88, sector: 'Technology' },
  { symbol: 'NVDA', name: 'NVIDIA Corp', qty: 20, avgEntryPrice: 870.00, currentPrice: 915.00, marketValue: 18300.00, unrealizedPL: 900.00, unrealizedPLPct: 5.17, sector: 'Technology' },
  { symbol: 'JPM', name: 'JPMorgan Chase', qty: 40, avgEntryPrice: 198.50, currentPrice: 195.40, marketValue: 7816.00, unrealizedPL: -124.00, unrealizedPLPct: -1.56, sector: 'Financials' },
  { symbol: 'JNJ', name: 'Johnson & Johnson', qty: 25, avgEntryPrice: 158.00, currentPrice: 156.20, marketValue: 3905.00, unrealizedPL: -45.00, unrealizedPLPct: -1.14, sector: 'Healthcare' },
  { symbol: 'XOM', name: 'Exxon Mobil', qty: 60, avgEntryPrice: 104.00, currentPrice: 107.50, marketValue: 6450.00, unrealizedPL: 210.00, unrealizedPLPct: 3.37, sector: 'Energy' },
];

export const mockOrders: Order[] = [
  { id: 'ord_001', symbol: 'TSLA', side: 'buy', qty: 15, type: 'limit', limitPrice: 245.00, status: 'pending', createdAt: '2026-05-20T09:30:00Z' },
  { id: 'ord_002', symbol: 'AMD', side: 'buy', qty: 40, type: 'limit', limitPrice: 162.00, status: 'pending', createdAt: '2026-05-20T10:15:00Z' },
  { id: 'ord_003', symbol: 'SPY', side: 'sell', qty: 10, type: 'market', status: 'filled', createdAt: '2026-05-19T14:00:00Z', filledAt: '2026-05-19T14:01:22Z' },
];

export const mockRecommendations: Recommendation[] = [
  { id: 'rec_001', symbol: 'NVDA', action: 'BUY', targetPrice: 980.00, currentPrice: 915.00, rationale: 'AI infrastructure spending acceleration. Data center revenue up 409% YoY. CUDA ecosystem moat is widening. Institutions accumulating.', strategyType: 1, strategyName: 'Fundamental', timestamp: '2026-05-20T08:00:00Z', horizon: '7-10 days', confidence: 88 },
  { id: 'rec_002', symbol: 'TSLA', action: 'WAIT', targetPrice: 260.00, currentPrice: 234.50, rationale: 'Oversold but lacking catalysts. Elon Tweet risk elevated. FSD robotaxi event pending — wait for confirmation before entering.', strategyType: 2, strategyName: 'Opportunistic', timestamp: '2026-05-20T08:00:00Z', horizon: '5-7 days', confidence: 72 },
  { id: 'rec_003', symbol: 'AMD', action: 'BUY', targetPrice: 175.00, currentPrice: 162.00, rationale: 'MI300X ramp gaining traction. Cloud capex cycle extending through 2026. Intel foundry failure = AMD gaining datacenter share.', strategyType: 1, strategyName: 'Fundamental', timestamp: '2026-05-20T08:00:00Z', horizon: '10-14 days', confidence: 81 },
  { id: 'rec_004', symbol: 'XOM', action: 'BUY', targetPrice: 115.00, currentPrice: 107.50, rationale: 'OPEC+ supply discipline + global demand resilience. Energy sector ETF flows positive. Carbon credit expansion favors integrated majors.', strategyType: 3, strategyName: 'Market Event', timestamp: '2026-05-20T08:00:00Z', horizon: '7 days', confidence: 75 },
  { id: 'rec_005', symbol: 'JPM', action: 'HOLD', targetPrice: 205.00, currentPrice: 195.40, rationale: 'Rate cut delay hurts net interest margin. Trading revenue strong but watch for credit deterioration in CRE portfolio. Maintain position.', strategyType: 1, strategyName: 'Fundamental', timestamp: '2026-05-20T08:00:00Z', horizon: '14 days', confidence: 68 },
  { id: 'rec_006', symbol: 'SPXL', action: 'SELL', targetPrice: 85.00, currentPrice: 91.20, rationale: 'Leveraged bull ETF expiring mid-year. Volatility crush incoming. Options skew extremely bearish near-term. Take profits.', strategyType: 5, strategyName: 'Quantitative Arbitrage', timestamp: '2026-05-20T08:00:00Z', horizon: '3-5 days', confidence: 79 },
  { id: 'rec_007', symbol: 'AREB', action: 'BUY', currentPrice: 18.40, rationale: 'Infrastructure bill payments resuming. Texas municipal bond fund with 6.2% yield. Political alignment: federal infrastructure spending acceleration.', strategyType: 4, strategyName: 'Politically Aligned', timestamp: '2026-05-20T08:00:00Z', horizon: '14-21 days', confidence: 76 },
];

export const mockWatchlist: WatchlistItem[] = [
  { symbol: 'AAPL', name: 'Apple Inc.', price: 182.50, change: 2.80, changePct: 1.56, high52: 199.62, low52: 164.08, volume: 52400000, sector: 'Technology' },
  { symbol: 'TSLA', name: 'Tesla Inc.', price: 234.50, change: -8.20, changePct: -3.38, high52: 278.98, low52: 138.80, volume: 98200000, sector: 'Consumer Discretionary' },
  { symbol: 'NVDA', name: 'NVIDIA Corp', price: 915.00, change: 15.30, changePct: 1.70, high52: 974.00, low52: 470.00, volume: 42100000, sector: 'Technology' },
  { symbol: 'SPY', name: 'SPDR S&P 500 ETF', price: 530.20, change: 3.40, changePct: 0.64, high52: 548.00, low52: 460.00, volume: 78200000, sector: 'ETF' },
  { symbol: 'AMD', name: 'Advanced Micro Devices', price: 162.00, change: 4.10, changePct: 2.60, high52: 227.30, low52: 121.00, volume: 48700000, sector: 'Technology' },
  { symbol: 'GLD', name: 'SPDR Gold Shares', price: 218.40, change: -1.20, changePct: -0.55, high52: 233.00, low52: 185.00, volume: 12800000, sector: 'Commodities' },
];