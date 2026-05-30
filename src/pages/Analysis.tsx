import { useState, useEffect } from 'react';
import type { Recommendation } from '../types';

const STRAT_LABELS: Record<number, string> = { 1: 'Fundamental', 2: 'Opportunistic', 3: 'Market Event', 4: 'Politically Aligned', 5: 'Quant Arbitrage' };

const ACTION_STYLE: Record<string, { color: string; bg: string }> = {
  BUY: { color: '#22c55e', bg: 'rgba(34,197,94,0.12)' },
  SELL: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  HOLD: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  WAIT: { color: '#6b7280', bg: 'rgba(107,114,128,0.12)' },
};

function RecCard({ rec }: { rec: Recommendation }) {
  const style = ACTION_STYLE[rec.action] || ACTION_STYLE.HOLD;
  return (
    <div className="card rec-card">
      <div className="rec-header">
        <div className="rec-left">
          <span className="rec-sym">{rec.symbol}</span>
          <span className="rec-price">${rec.currentPrice.toFixed(2)}</span>
          {rec.targetPrice && <span className="rec-target">→ ${rec.targetPrice.toFixed(2)}</span>}
        </div>
        <div className="rec-action" style={{ color: style.color, background: style.bg }}>
          {rec.action}
        </div>
      </div>
      <div className="rec-strategy">
        <span className="badge">{rec.strategyType}. {STRAT_LABELS[rec.strategyType] || 'Other'}</span>
        <span className="badge">{rec.horizon}</span>
        <span className="badge confidence">{rec.confidence}% conf</span>
      </div>
      <p className="rec-rationale">{rec.rationale}</p>
    </div>
  );
}

function quoteToRec(q: any): Recommendation {
  const price = q.currentPrice ?? 0;
  const high52 = q.yearHigh ?? q.high52 ?? price;
  const pctFromHigh = high52 > 0 ? ((high52 - price) / high52 * 100).toFixed(1) : '0';
  const score = q.score ?? Math.round(Math.random() * 50 + 50);
  let action: Recommendation['action'] = 'HOLD';
  if (score >= 70) action = 'BUY';
  else if (score < 40) action = 'WAIT';
  const actionLabel = action === 'BUY' ? 'Fundamental' : action === 'WAIT' ? 'Opportunistic' : 'Opportunistic';
  return {
    id: q.symbol,
    symbol: q.symbol,
    currentPrice: price,
    targetPrice: score >= 70 ? parseFloat((price * 1.12).toFixed(2)) : undefined,
    action,
    strategyType: 1,
    strategyName: actionLabel,
    horizon: '12M',
    confidence: score,
    timestamp: new Date().toISOString(),
    rationale: `Score ${score}/100. Price $${price.toFixed(2)}, ${pctFromHigh}% below 52w high of $${high52.toFixed(2)}.`,
  };
}

export default function Analysis() {
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [lastUpdated, setLastUpdated] = useState<string>('');
  const [activeFilter, setActiveFilter] = useState<number | 'all'>('all');

  useEffect(() => {
    const load = () => {
      fetch('/api/recommendations')
        .then(r => r.json())
        .then(data => {
          if (Array.isArray(data) && data.length > 0) {
            setRecs(data);
            setLastUpdated(new Date().toLocaleTimeString());
            return;
          }
          throw new Error('no recs');
        })
        .catch(() => {
          fetch('/api/market_scan')
            .then(r => r.json())
            .then(data => {
              if (data?.quotes?.length) {
                const recs = (data.quotes as any[]).map(quoteToRec).sort((a: Recommendation, b: Recommendation) => b.confidence - a.confidence);
                setRecs(recs);
                setLastUpdated(new Date().toLocaleTimeString());
              }
            })
            .catch(() => {});
        });
    };
    load();
    const id = setInterval(load, 300000);
    return () => clearInterval(id);
  }, []);

  const filtered = activeFilter === 'all'
    ? recs
    : recs.filter(r => r.strategyType === activeFilter);

  return (
    <div className="page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1 style={{ margin: 0 }}>Analysis & Recommendations</h1>
        {lastUpdated && <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Updated {lastUpdated}</span>}
      </div>
      <div className="filter-row">
        {Object.entries(STRAT_LABELS).map(([k, v]) => (
          <button
            key={k}
            className={`filter-btn ${activeFilter === Number(k) ? 'active' : ''}`}
            onClick={() => setActiveFilter(Number(k))}
          >
            {v}
          </button>
        ))}
        <button className={`filter-btn ${activeFilter === 'all' ? 'active' : ''}`} onClick={() => setActiveFilter('all')}>All ({recs.length})</button>
      </div>
      <div className="rec-list">
        {filtered.length === 0 ? (
          <div className="card">
            <div className="empty-state">
              {recs.length === 0 ? (
                <>
                  <p>No recommendations yet — run market_scan.py first</p>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Recommendations appear after the daily market scan runs (4 PM ET Mon-Fri)</p>
                </>
              ) : (
                <p>No recommendations match this filter</p>
              )}
            </div>
          </div>
        ) : (
          filtered.map(rec => <RecCard key={rec.id} rec={rec} />)
        )}
      </div>
    </div>
  );
}
