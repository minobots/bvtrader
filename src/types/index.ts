export interface Position {
  symbol: string;
  name: string;
  qty: number;
  avgEntryPrice: number;
  currentPrice: number;
  marketValue: number;
  unrealizedPL: number;
  unrealizedPLPct: number;
  sector: string;
}

export interface Order {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  qty: number;
  type: 'market' | 'limit';
  limitPrice?: number;
  status: 'pending' | 'filled' | 'cancelled' | 'rejected';
  createdAt: string;
  filledAt?: string;
}

export interface Recommendation {
  id: string;
  symbol: string;
  action: 'BUY' | 'SELL' | 'HOLD' | 'WAIT';
  targetPrice?: number;
  currentPrice: number;
  rationale: string;
  strategyType: 1 | 2 | 3 | 4 | 5;
  strategyName: string;
  timestamp: string;
  horizon: string;
  confidence: number; // 0-100
}

export interface PortfolioSummary {
  totalValue: number;
  cash: number;
  equity: number;
  dayChange: number;
  dayChangePct: number;
}

export interface WatchlistItem {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePct: number;
  high52: number;
  low52: number;
  volume: number;
  sector: string;
}