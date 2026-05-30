import { useState, useEffect } from 'react';
import Portfolio from './pages/Portfolio';
import Analysis from './pages/Analysis';
import Approvals from './pages/Approvals';
import MarketWatch from './pages/MarketWatch';
import Library from './pages/Library';
import Nav from './components/Nav';
import './App.css';

type Page = 'portfolio' | 'analysis' | 'approvals' | 'market' | 'library';

function fmt(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(n);
}

function isMarketOpen(): boolean {
  const now = new Date();
  const etHour = parseInt(
    new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', hour12: false })
      .format(now)
  );
  const etWeekday = now.getDay();
  return etWeekday >= 1 && etWeekday <= 5 && etHour >= 9 && etHour < 16;
}

interface HeaderSummary {
  totalValue: number;
  cash: number;
  dayChange: number;
  dayChangePct: number;
  totalGain: number;
  totalGainPct: number;
  lastUpdated: string;
}

export default function App() {
  const [page, setPage] = useState<Page>('portfolio');
  const [headerData, setHeaderData] = useState<HeaderSummary | null>(null);
  const [marketOpen] = useState(isMarketOpen());

  useEffect(() => {
    const load = () => {
      fetch('/api/summary')
        .then(r => r.json())
        .then(d => {
          if (d && d.totalValue !== undefined) {
            setHeaderData({
              totalValue: d.totalValue,
              cash: d.cash,
              dayChange: d.dayChange ?? 0,
              dayChangePct: d.dayChangePct ?? 0,
              totalGain: d.totalGain ?? 0,
              totalGainPct: d.totalGainPct ?? 0,
              lastUpdated: new Date().toLocaleTimeString('en-US', { timeZone: 'America/New_York' }),
            });
          }
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="app">
      {/* ── Top Status Bar ── */}
      <div className="status-bar">
        <div className="status-left">
          <span className="status-brand">BV</span>
          {headerData ? (
            <>
              <span className="status-sep">·</span>
              <span className="status-item">
                <span className="status-label">Value</span>
                <span className="status-value">{fmt(headerData.totalValue)}</span>
              </span>
              <span className="status-item">
                <span className="status-label">Day</span>
                <span className={`status-value ${headerData.dayChange >= 0 ? 'up' : 'down'}`}>
                  {headerData.dayChange >= 0 ? '+' : ''}{fmt(headerData.dayChange)} ({headerData.dayChangePct.toFixed(2)}%)
                </span>
              </span>
              <span className="status-item">
                <span className="status-label">Cash</span>
                <span className="status-value">{fmt(headerData.cash)}</span>
              </span>
            </>
          ) : (
            <span className="status-loading">Loading…</span>
          )}
        </div>
        <div className="status-right">
          <span className="status-updated">
            {headerData ? `${headerData.lastUpdated} ET` : '—'}
          </span>
          <span className={`market-badge ${marketOpen ? 'open' : 'closed'}`}>
            {marketOpen ? '● Live' : '● Closed'}
          </span>
        </div>
      </div>

      <Nav current={page} onNavigate={setPage} />
      <main className="main">
        {page === 'portfolio' && <Portfolio />}
        {page === 'analysis' && <Analysis />}
        {page === 'approvals' && <Approvals />}
        {page === 'market' && <MarketWatch />}
        {page === 'library' && <Library />}
      </main>
    </div>
  );
}

export type { Page };
