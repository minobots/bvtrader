import { useState, useEffect } from 'react';

interface LibSymbol {
  symbol: string;
  name: string;
  assetType: string;
  exchange: string;
  sector: string;
  industry: string;
  marketCap: number | null;
  rule1Score: number | null;
  compositeScore: number | null;
  scanStatus: string;
  rule5Score: number | null;
  rule2Score: number | null;
  rule3Score: number | null;
  rule4Score: number | null;
  rule6Score: number | null;
  currentPrice: number | null;
  fiftyTwoHigh: number | null;
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

function ScoreBar({ score, threshold = 60 }: { score: number | null; threshold?: number }) {
  if (score == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const pct = Math.min(100, Math.max(0, score));
  const color = score >= threshold ? 'up' : score >= 40 ? 'hold' : 'down';
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

function price(v: number | null) {
  if (v == null) return '—';
  if (v >= 1000) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (v >= 1) return `$${v.toFixed(2)}`;
  if (v >= 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(6)}`;
}

type SortKey = 'symbol' | 'compositeScore' | 'rule1Score' | 'rule5Score' | 'currentPrice' | 'sector';

type ScanState = { idle: true } | { running: true } | { done: true; ok: boolean; message: string };

export default function Library() {
  const [symbols, setSymbols] = useState<LibSymbol[]>([]);
  const [count, setCount] = useState(0);
  const [cryptoCount, setCryptoCount] = useState(0);
  const [stockCount, setStockCount] = useState(0);
  const [filter, setFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState<'all' | 'stock' | 'etf' | 'crypto'>('all');
  const [sortKey, setSortKey] = useState<SortKey>('compositeScore');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>('');
  const [scanState, setScanState] = useState<ScanState>({ idle: true });

  useEffect(() => {
    const load = () => {
      fetch('/api/library')
        .then(r => r.json())
        .then(d => {
          setSymbols(d.symbols || []);
          setCount(d.count || 0);
          setCryptoCount(d.cryptoCount || 0);
          setStockCount(d.stockCount || 0);
          setLoading(false);
          setLastUpdated(new Date().toLocaleTimeString());
        })
        .catch(() => setLoading(false));
    };
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, []);

  const triggerScan = async () => {
    setScanState({ running: true });
    try {
      const res = await fetch('/api/scan', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        setScanState({ done: true, ok: true, message: `Scan complete. Reload page to see new data.` });
        setTimeout(() => {
          fetch('/api/library')
            .then(r => r.json())
            .then(d => {
              setSymbols(d.symbols || []);
              setCount(d.count || 0);
              setLastUpdated(new Date().toLocaleTimeString());
            })
            .catch(() => {});
        }, 2000);
      } else {
        setScanState({ done: true, ok: false, message: data.message || 'Scan failed' });
      }
    } catch {
      setScanState({ done: true, ok: false, message: 'Network error' });
    }
    setTimeout(() => setScanState({ idle: true }), 10000);
  };

  const filtered = symbols
    .filter(s => {
      if (typeFilter !== 'all' && s.assetType !== typeFilter) return false;
      if (!filter) return true;
      const q = filter.toLowerCase();
      return s.symbol.toLowerCase().includes(q) || (s.name || '').toLowerCase().includes(q) || (s.sector || '').toLowerCase().includes(q);
    })
    .sort((a, b) => {
      let av: any = a[sortKey];
      let bv: any = b[sortKey];
      if (av == null) av = -Infinity;
      if (bv == null) bv = -Infinity;
      if (typeof av === 'string') {
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('desc'); }
  }

  const isCryptoView = typeFilter === 'crypto';

  return (
    <div className="page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <h1 style={{ marginBottom: 4 }}>Library</h1>
          <p style={{ color: 'var(--text-muted)', margin: 0, fontSize: '0.85rem' }}>
            {loading ? 'Loading…' : `${count} symbols scored (${stockCount} stocks/ETFs · ${cryptoCount} crypto)`}
            {lastUpdated && <span style={{ fontSize: '0.7rem', marginLeft: 4 }}> · Updated {lastUpdated}</span>}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['all', 'stock', 'etf', 'crypto'] as const).map(t => (
            <button key={t} className={`btn-sm ${typeFilter === t ? 'active' : ''}`}
              onClick={() => setTypeFilter(t)}>
              {t === 'all' ? 'All' : t === 'stock' ? 'Stocks' : t === 'etf' ? 'ETFs' : '🪙 Crypto'}
            </button>
          ))}
        </div>
      </div>

      <input
        className="search-input"
        placeholder={isCryptoView ? "Filter by symbol, name, or sector…" : "Filter by symbol or name…"}
        value={filter}
        onChange={e => setFilter(e.target.value)}
        style={{ marginBottom: 12, width: '100%', maxWidth: 320 }}
      />

      {!loading && symbols.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <p>Library is empty — no symbols scored yet</p>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Portfolio Library Builder runs on weekdays at 9 AM ET.
              Crypto scoring runs every 4 hours.
              {'running' in scanState && scanState.running ? ' Scanning…' : ''}
            </p>
            {'done' in scanState && (
              <div style={{
                marginTop: 8, padding: '0.5rem 1rem', borderRadius: 6, fontSize: '0.85rem',
                background: scanState.ok ? 'var(--up-soft)' : 'var(--down-soft)',
                color: scanState.ok ? 'var(--up)' : 'var(--down)',
              }}>
                {scanState.ok ? '✓' : '✗'} {scanState.message}
              </div>
            )}
            <button className="btn-approve" onClick={triggerScan} disabled={'running' in scanState && scanState.running}
              style={{ marginTop: 8, opacity: ('running' in scanState && scanState.running) ? 0.5 : 1 }}>
              {'running' in scanState && scanState.running ? 'Scanning…' : 'Run Full Scan Now'}
            </button>
          </div>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          {'running' in scanState && scanState.running && (
            <div style={{ padding: '0.5rem 1rem', background: 'var(--accent-soft)', color: 'var(--accent)', fontSize: '0.8rem', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>
              ⏳ Scan running in background… data will refresh when complete.
            </div>
          )}
          {'done' in scanState && scanState.done && (
            <div style={{
              padding: '0.5rem 1rem',
              background: scanState.ok ? 'var(--up-soft)' : 'var(--down-soft)',
              color: scanState.ok ? 'var(--up)' : 'var(--down)',
              fontSize: '0.8rem',
              borderBottom: '1px solid var(--border)',
              fontWeight: 600,
            }}>
              {scanState.ok ? '✓' : '✗'} {scanState.message}
            </div>
          )}
          <table className="data-table" style={{ minWidth: isCryptoView ? 600 : 900 }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'left', cursor: 'pointer' }} onClick={() => toggleSort('symbol')}>Symbol {sortKey === 'symbol' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</th>
                <th style={{ textAlign: 'left' }}>Name</th>
                {!isCryptoView && <th style={{ textAlign: 'left' }}>Type</th>}
                {isCryptoView && <th style={{ textAlign: 'left', cursor: 'pointer' }} onClick={() => toggleSort('sector')}>Sector {sortKey === 'sector' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</th>}
                <th style={{ textAlign: 'left', cursor: 'pointer' }} onClick={() => toggleSort('compositeScore')}>Score {sortKey === 'compositeScore' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</th>
                <th style={{ textAlign: 'left' }}>Signal</th>
                {isCryptoView ? (
                  <>
                    <th style={{ textAlign: 'right', cursor: 'pointer' }} onClick={() => toggleSort('currentPrice')}>Price {sortKey === 'currentPrice' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</th>
                    <th style={{ textAlign: 'right' }}>ATH</th>
                    <th style={{ textAlign: 'right' }}>R2</th>
                    <th style={{ textAlign: 'right' }}>R5 Trend</th>
                    <th style={{ textAlign: 'right' }}>R6 Cycle</th>
                  </>
                ) : (
                  <>
                    <th style={{ textAlign: 'right', cursor: 'pointer' }} onClick={() => toggleSort('rule1Score')}>R1 {sortKey === 'rule1Score' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</th>
                    <th style={{ textAlign: 'right' }}>P/E</th>
                    <th style={{ textAlign: 'right' }}>Fwd P/E</th>
                    <th style={{ textAlign: 'right' }}>PEG</th>
                    <th style={{ textAlign: 'right' }}>EPS Grw</th>
                    <th style={{ textAlign: 'right' }}>ROE</th>
                    <th style={{ textAlign: 'right' }}>Profit Mrg</th>
                    <th style={{ textAlign: 'right' }}>D/E</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={isCryptoView ? 8 : 12} style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)' }}>
                  {loading ? 'Loading…' : 'No symbols match'}</td></tr>
              ) : filtered.map(s => (
                <tr key={s.symbol}>
                  <td className="sym">{s.symbol}</td>
                  <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}
                      title={s.name || s.symbol}>{s.name || s.symbol}</td>
                  {!isCryptoView && <td><span className={`tag ${s.assetType}`}>{s.assetType}</span></td>}
                  {isCryptoView && <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{s.sector || s.industry || '—'}</td>}
                  <td><ScoreBar score={s.compositeScore ?? s.rule1Score} threshold={isCryptoView ? 60 : 65} /></td>
                  <td>
                    {s.scanStatus ? (
                      <span className={`tag ${s.scanStatus === 'buy' ? 'up' : s.scanStatus === 'avoid' ? 'down' : 'hold'}`}>
                        {s.scanStatus.toUpperCase()}
                      </span>
                    ) : '—'}
                  </td>
                  {isCryptoView ? (
                    <>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>{price(s.currentPrice)}</td>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>{price(s.fiftyTwoHigh)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{s.rule2Score?.toFixed(1) ?? '—'}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{s.rule5Score?.toFixed(1) ?? '—'}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{s.rule6Score?.toFixed(1) ?? '—'}</td>
                    </>
                  ) : (
                    <>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>{s.peRatio?.toFixed(1) ?? '—'}</td>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>{s.forwardPe?.toFixed(1) ?? '—'}</td>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>{s.pegRatio?.toFixed(2) ?? '—'}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{pct(s.epsGrowth)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{pct(s.roe)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{pct(s.profitMargin)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{s.debtToEquity?.toFixed(1) ?? '—'}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
