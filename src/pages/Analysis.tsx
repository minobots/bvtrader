
import { mockRecommendations } from '../data/mockData';
import type { Recommendation } from '../types';

const STRAT_LABELS = { 1: 'Fundamental', 2: 'Opportunistic', 3: 'Market Event', 4: 'Politically Aligned', 5: 'Quant Arbitrage' };

const ACTION_STYLE: Record<string, { color: string; bg: string }> = {
  BUY: { color: '#10B981', bg: 'rgba(16,185,129,0.1)' },
  SELL: { color: '#EF4444', bg: 'rgba(239,68,68,0.1)' },
  HOLD: { color: '#F59E0B', bg: 'rgba(245,158,11,0.1)' },
  WAIT: { color: '#6B7280', bg: 'rgba(107,114,128,0.1)' },
};

function RecCard({ rec }: { rec: Recommendation }) {
  const style = ACTION_STYLE[rec.action] || ACTION_STYLE.HOLD;
  return (
    <div className="card rec-card">
      <div className="rec-header">
        <div className="rec-left">
          <span className="rec-sym">{rec.symbol}</span>
          <span className="rec-price">{rec.currentPrice}</span>
          {rec.targetPrice && <span className="rec-target">→ {rec.targetPrice}</span>}
        </div>
        <div className="rec-action" style={{ color: style.color, background: style.bg }}>
          {rec.action}
        </div>
      </div>
      <div className="rec-strategy">
        <span className="badge">{rec.strategyType}. {STRAT_LABELS[rec.strategyType]}</span>
        <span className="badge">{rec.horizon}</span>
        <span className="badge confidence">{rec.confidence}% confidence</span>
      </div>
      <p className="rec-rationale">{rec.rationale}</p>
    </div>
  );
}

export default function Analysis() {
  return (
    <div className="page">
      <h1>Analysis & Recommendations</h1>
      <div className="filter-row">
        {Object.entries(STRAT_LABELS).map(([k, v]) => (
          <button key={k} className="filter-btn">{v}</button>
        ))}
        <button className="filter-btn active">All</button>
      </div>
      <div className="rec-list">
        {mockRecommendations.map(rec => <RecCard key={rec.id} rec={rec} />)}
      </div>
    </div>
  );
}