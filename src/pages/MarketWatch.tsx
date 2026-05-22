import { TrendingUp, TrendingDown } from 'lucide-react';
import { mockWatchlist } from '../data/mockData';

function fmt(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}
function fmtVol(n: number) {
  return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(0) + 'K' : n;
}

export default function MarketWatch() {
  return (
    <div className="page">
      <h1>Market Watch</h1>
      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Name</th>
              <th>Sector</th>
              <th>Price</th>
              <th>Change</th>
              <th>52W High</th>
              <th>52W Low</th>
              <th>Volume</th>
            </tr>
          </thead>
          <tbody>
            {mockWatchlist.map(w => (
              <tr key={w.symbol}>
                <td className="sym">{w.symbol}</td>
                <td>{w.name}</td>
                <td>{w.sector}</td>
                <td>{fmt(w.price)}</td>
                <td className={w.change >= 0 ? 'up' : 'down'}>
                  {w.change >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  {' '}{w.change >= 0 ? '+' : ''}{fmt(w.change)} ({w.changePct.toFixed(2)}%)
                </td>
                <td>{fmt(w.high52)}</td>
                <td>{fmt(w.low52)}</td>
                <td>{fmtVol(w.volume)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}