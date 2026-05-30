import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import type { WatchlistItem } from '../types';

function fmt(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}
function fmtVol(n: number) {
  return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(0) + 'K' : String(n);
}

type SortKey = 'score' | 'price' | 'changePct';
type FilterKey = 'all' | 'green' | 'yellow' | 'red';

function scoreColor(score: number) {
  if (score >= 70) return 'var(--up)';
  if (score >= 40) return 'var(--warn)';
  return 'var(--down)';
}

export default function MarketWatch() {
  const [quotes, setQuotes] = useState<WatchlistItem[]>([]);
  const [scores, setScores] = useState<Record<string, number>>({});
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [filter, setFilter] = useState<FilterKey>('all');

  useEffect(() => {
    const load = () => {
      fetch('/api/market_scan')
        .then(r => r.json())
        .then(data => {
          if (data?.quotes?.length) {
            const items: WatchlistItem[] = data.quotes.map((q: any) => ({
              symbol: q.symbol,
              name: q.symbol,
              price: q.currentPrice ?? q.price ?? 0,
              change: q.change ?? 0,
              changePct: q.changePct ?? q.changesPercentage ?? 0,
              high52: q.yearHigh ?? q.high52 ?? 0,
              low52: q.yearLow ?? q.low52 ?? 0,
              volume: q.volume ?? 0,
              sector: q.sector ?? 'Unknown',
            }));
            setQuotes(items);
            const scoreMap: Record<string, number> = {};
            if (data.report?.scores) {
              Object.entries(data.report.scores).forEach(([sym, sc]) => {
                scoreMap[sym] = sc as number;
              });
            }
            setScores(scoreMap);
          } else {
            setQuotes([]);
          }
        })
        .catch(() => setQuotes([]));
    };
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, []);

  const filtered = quotes.filter(q => {
    const sc = scores[q.symbol] ?? 50;
    if (filter === 'green') return sc >= 70;
    if (filter === 'yellow') return sc >= 40 && sc < 70;
    if (filter === 'red') return sc < 40;
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    if (sortKey === 'score') return (scores[b.symbol] ?? 0) - (scores[a.symbol] ?? 0);
    if (sortKey === 'price') return b.price - a.price;
    return b.changePct - a.changePct;
  });

  return (
    <div className="page">
      <h1>Market Watch</h1>
      {quotes.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <p>No market data — market may be closed or scan hasn't run yet.</p>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Data refreshes every 60 seconds when market is open.</p>
          </div>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem', alignItems: 'center' }}>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginRight: '0.25rem', fontWeight: 500 }}>Sort:</span>
            {([['score','Score'],['price','Price'],['changePct','Change%']] as [SortKey,string][]).map(([k, label]) => (
              <button key={k} className={`filter-btn ${sortKey === k ? 'active' : ''}`} onClick={() => setSortKey(k)}>{label}</button>
            ))}
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: '0.75rem', marginRight: '0.25rem', fontWeight: 500 }}>Signal:</span>
            {([['all','All'],['green','🟢 Green'],['yellow','🟡 Yellow'],['red','🔴 Red']] as [FilterKey,string][]).map(([k, label]) => (
              <button key={k} className={`filter-btn ${filter === k ? 'active' : ''}`} onClick={() => setFilter(k)}>{label}</button>
            ))}
          </div>
          <div className="card" style={{ padding: 0 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Sector</th>
                  <th>Score</th>
                  <th>Price</th>
                  <th>Change</th>
                  <th>52W High</th>
                  <th>52W Low</th>
                  <th>Volume</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(w => {
                  const sc = scores[w.symbol] ?? 50;
                  return (
                    <tr key={w.symbol}>
                      <td className="sym">{w.symbol}</td>
                      <td>{w.sector}</td>
                      <td>
                        <span style={{ fontWeight: 700, color: scoreColor(sc), fontFamily: 'JetBrains Mono, monospace', fontSize: '0.85rem' }}>
                          {sc}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace' }}>{fmt(w.price)}</td>
                      <td className={w.change >= 0 ? 'up' : 'down'} style={{ fontFamily: 'JetBrains Mono, monospace' }}>
                        {w.change >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                        {' '}{w.change >= 0 ? '+' : ''}{fmt(w.change)} ({w.changePct.toFixed(2)}%)
                      </td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace' }}>{fmt(w.high52)}</td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace' }}>{fmt(w.low52)}</td>
                      <td>{fmtVol(w.volume)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
