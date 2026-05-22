import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts';
import { mockPortfolio, mockPositions } from '../data/mockData';
import type { PortfolioSummary, Position } from '../types';

const SECTOR_COLORS = ['#4F46E5', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899'];

function fmt(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}

export default function Portfolio() {
  const [summary, setSummary] = useState<PortfolioSummary>(mockPortfolio);
  const [positions, setPositions] = useState<Position[]>(mockPositions);

  useEffect(() => {
    Promise.all([
      fetch('/api/summary').then(r => r.json()).catch(() => null),
      fetch('/api/positions').then(r => r.json()).catch(() => null),
    ]).then(([s, p]) => {
      if (s && s.totalValue !== undefined) setSummary(s);
      if (p && p.length > 0) setPositions(p);
    });
  }, []);

  const sectorData = positions.reduce((acc, pos) => {
    const found = acc.find(d => d.name === pos.sector);
    if (found) found.value += pos.marketValue;
    else acc.push({ name: pos.sector, value: pos.marketValue });
    return acc;
  }, [] as { name: string; value: number }[]);

  // Backend now provides totalGain/totalGainPct computed from real starting capital
  const totalGain = summary.totalGain ?? (summary.totalValue - summary.startingCapital);
  const totalGainPct = summary.totalGainPct ?? 0;

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
          <h3>Performance</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={[]}>
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
              <Tooltip formatter={(v: number) => fmt(v)} />
              <Line type="monotone" dataKey="value" stroke="#4F46E5" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="card chart-card">
          <h3>Allocation</h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={sectorData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={({ name }) => name}>
                {sectorData.map((_, i) => <Cell key={i} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} />)}
              </Pie>
              <Legend />
            </PieChart>
          </ResponsiveContainer>
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
                <td colSpan={7} style={{ textAlign: 'center', color: '#6b7280' }}>
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
                  <td>{fmt(pos.marketValue)}</td>
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