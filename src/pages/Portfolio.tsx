import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts';
import { mockPortfolio, mockPositions } from '../data/mockData';
import type { PortfolioSummary, Position } from '../types';

const SECTOR_COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];

function fmt(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}

export default function Portfolio() {
  const [summary, setSummary] = useState<PortfolioSummary>(mockPortfolio);
  const [positions, setPositions] = useState<Position[]>(mockPositions);

  useEffect(() => {
    const load = () => Promise.all([
      fetch('/api/summary').then(r => r.json()).catch(() => null),
      fetch('/api/positions').then(r => r.json()).catch(() => null),
    ]).then(([s, p]) => {
      if (s && s.totalValue !== undefined) setSummary(s);
      if (p && p.length > 0) setPositions(p);
    });
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, []);

  const sectorData = positions.reduce((acc, pos) => {
    const found = acc.find(d => d.name === pos.sector);
    if (found) found.value += pos.marketValue;
    else acc.push({ name: pos.sector, value: pos.marketValue });
    return acc;
  }, [] as { name: string; value: number }[]);

  const totalGain = summary.totalGain ?? (summary.totalValue - summary.startingCapital);
  const totalGainPct = summary.totalGainPct ?? 0;

  const allocData = positions.map(p => ({ name: p.symbol, value: p.marketValue }));

  return (
    <div className="page">
      <h1>Portfolio Overview</h1>

      <div className="summary-cards">
        <div className="card summary-card">
          <div className="card-label">Total Value</div>
          <div className="card-value">{fmt(summary.totalValue)}</div>
        </div>
        <div className="card summary-card">
          <div className="card-label">Cash Available</div>
          <div className="card-value">{fmt(summary.cash)}</div>
        </div>
        <div className="card summary-card">
          <div className="card-label">Day Change</div>
          <div className={`card-value ${summary.dayChange >= 0 ? 'up' : 'down'}`}>
            {summary.dayChange >= 0 ? '+' : ''}{fmt(summary.dayChange)} ({summary.dayChangePct.toFixed(2)}%)
          </div>
        </div>
        <div className="card summary-card">
          <div className="card-label">Total Gain/Loss</div>
          <div className={`card-value ${totalGain >= 0 ? 'up' : 'down'}`}>
            {totalGain >= 0 ? '+' : ''}{fmt(totalGain)} ({totalGainPct.toFixed(2)}%)
          </div>
        </div>
      </div>

      <div className="charts-row">
        <div className="card chart-card">
          <h3>Position Allocation</h3>
          {allocData.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '2rem' }}>No positions — paper account not yet deployed</div>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={allocData} layout="vertical" margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
                <XAxis type="number" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} tickFormatter={v => `$${(((v as number)||0)/1000).toFixed(0)}k`} axisLine={{ stroke: 'var(--border)' }} tickLine={false} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-secondary)', fontFamily: 'JetBrains Mono, monospace' }} width={50} axisLine={false} tickLine={false} />
                <Tooltip />
                <Bar dataKey="value" fill="#6366f1" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card chart-card">
          <h3>Sector Breakdown</h3>
          {sectorData.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '2rem' }}>No positions</div>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={sectorData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} innerRadius={45} label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}>
                  {sectorData.map((_, i) => <Cell key={i} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} />)}
                </Pie>
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Holdings</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Name</th>
              <th>Shares</th>
              <th>Avg Entry</th>
              <th>Current</th>
              <th>Market Value</th>
              <th>Gain/Loss</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                  No positions — paper account not yet deployed
                </td>
              </tr>
            ) : (
              positions.map(pos => (
                <tr key={pos.symbol}>
                  <td className="sym">{pos.symbol}</td>
                  <td>{pos.name}</td>
                  <td>{pos.qty}</td>
                  <td>{fmt(pos.avgEntryPrice)}</td>
                  <td>{fmt(pos.currentPrice)}</td>
                  <td style={{ fontWeight: 600, color: 'var(--text)' }}>{fmt(pos.marketValue)}</td>
                  <td className={pos.unrealizedPL >= 0 ? 'up' : 'down'}>
                    {pos.unrealizedPL >= 0 ? '+' : ''}{fmt(pos.unrealizedPL)} ({pos.unrealizedPLPct.toFixed(2)}%)
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
