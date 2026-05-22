import { useState, useEffect } from 'react';

interface LibSymbol {
  symbol: string;
  name: string;
  assetType: string;
  exchange: string;
  rule1Score: number | null;
  peRatio: number | null;
  forwardPe: number | null;
  pegRatio: number | null;
  epsGrowth: number | null;
  revGrowth: number | null;
  roe: number | null;
  profitMargin: number | null;
  debtToEquity: number | null;
  divYield: number | null;
}

function ScoreBar({ score }: { score: number | null }) {
  if (score == null) return <span className="na">—</span>;
  const pct = Math.min(100, Math.max(0, score));
  const color = score >= 60 ? 'up' : score >= 35 ? 'hold' : 'down';
  return (
    <div className="score-bar-wrap">
      <div className={`score-bar ${color}`} style={{ width: `${pct}%` }} />
      <span className="score-val">{score.toFixed(1)}</span>
    </div>
  );
}

function pct(v: number | null, suffix = '%') {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}${suffix}`;
}

const COLUMNS: { key: keyof LibSymbol; label: string; align?: 'right' }[] = [
  { key: 'symbol',       label: 'Symbol' },
  { key: 'name',         label: 'Name' },
  { key: 'assetType',    label: 'Type' },
  { key: 'rule1Score',   label: 'R1 Score' },
  { key: 'peRatio',      label: 'P/E',       align: 'right' },
  { key: 'forwardPe',     label: 'Fwd P/E',   align: 'right' },
  { key: 'pegRatio',      label: 'PEG',       align: 'right' },
  { key: 'epsGrowth',     label: 'EPS Grw',   align: 'right' },
  { key: 'revGrowth',     label: 'Rev Grw',   align: 'right' },
  { key: 'roe',           label: 'ROE',       align: 'right' },
  { key: 'profitMargin',  label: 'Profit Mrg', align: 'right' },
  { key: 'debtToEquity',  label: 'D/E',        align: 'right' },
  { key: 'divYield',      label: 'Div Yield',  align: 'right' },
];

export default function Library() {
  const [symbols, setSymbols] = useState<LibSymbol[]>([]);
  const [count, setCount] = useState(0);
  const [filter, setFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState<'all' | 'stock' | 'etf'>('all');
  const [sortKey, setSortKey] = useState<keyof LibSymbol>('rule1Score');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/library')
      .then(r => r.json())
      .then(d => { setSymbols(d.symbols || []); setCount(d.count || 0); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const filtered = symbols
    .filter(s => {
      if (typeFilter !== 'all' && s.assetType !== typeFilter) return false;
      if (!filter) return true;
      const q = filter.toLowerCase();
      return s.symbol.toLowerCase().includes(q) || (s.name || '').toLowerCase().includes(q);
    })
    .sort((a, b) => {
      const av = a[sortKey] ?? -Infinity;
      const bv = b[sortKey] ?? -Infinity;
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });

  function toggleSort(key: keyof LibSymbol) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('desc'); }
  }

  return (
    <div className="page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h1>Library</h1>
          <p style={{ color: 'var(--text-muted)', margin: 0 }}>
            {loading ? 'Loading...' : `${count} symbols scored · Top 200 by Rule 1`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['all', 'stock', 'etf'] as const).map(t => (
            <button key={t} className={`btn-sm ${typeFilter === t ? 'active' : ''}`}
              onClick={() => setTypeFilter(t)}>
              {t === 'all' ? 'All' : t === 'stock' ? 'Stocks' : 'ETFs'}
            </button>
          ))}
        </div>
      </div>

      <input
        className="search-input"
        placeholder="Filter by symbol or name…"
        value={filter}
        onChange={e => setFilter(e.target.value)}
        style={{ marginBottom: 12, width: '100%', maxWidth: 320 }}
      />

      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        <table className="data-table" style={{ minWidth: 900 }}>
          <thead>
            <tr>
              {COLUMNS.map(col => (
                <th key={col.key} style={{ textAlign: col.align || 'left', cursor: 'pointer', whiteSpace: 'nowrap' }}
                    onClick={() => toggleSort(col.key)}>
                  {col.label} {sortKey === col.key ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={COLUMNS.length} style={{ textAlign: 'center', padding: 24 }}>
                {loading ? 'Loading…' : 'No symbols match'}</td></tr>
            ) : filtered.map(s => (
              <tr key={s.symbol}>
                <td className="sym">{s.symbol}</td>
                <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={s.name || s.symbol}>{s.name || s.symbol}</td>
                <td><span className={`tag ${s.assetType}`}>{s.assetType}</span></td>
                <td><ScoreBar score={s.rule1Score} /></td>
                <td style={{ textAlign: 'right' }}>{s.peRatio?.toFixed(1) ?? '—'}</td>
                <td style={{ textAlign: 'right' }}>{s.forwardPe?.toFixed(1) ?? '—'}</td>
                <td style={{ textAlign: 'right' }}>{s.pegRatio?.toFixed(2) ?? '—'}</td>
                <td style={{ textAlign: 'right' }}>{pct(s.epsGrowth)}</td>
                <td style={{ textAlign: 'right' }}>{pct(s.revGrowth)}</td>
                <td style={{ textAlign: 'right' }}>{pct(s.roe)}</td>
                <td style={{ textAlign: 'right' }}>{pct(s.profitMargin)}</td>
                <td style={{ textAlign: 'right' }}>{s.debtToEquity?.toFixed(1) ?? '—'}</td>
                <td style={{ textAlign: 'right' }}>{pct(s.divYield)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}