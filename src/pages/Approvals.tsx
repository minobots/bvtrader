import { useState, useEffect, useCallback } from 'react';
import { CheckCircle, XCircle, Clock } from 'lucide-react';
import type { Order } from '../types';

function fmtTime(iso: string) {
  try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch { return '—'; }
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { color: string; label: string }> = {
    accepted: { color: 'var(--up)', label: 'Accepted' },
    new: { color: 'var(--warn)', label: 'New' },
    partially_filled: { color: 'var(--warn)', label: 'Partial' },
    pending: { color: 'var(--warn)', label: 'Pending' },
    filled: { color: 'var(--up)', label: 'Filled' },
    cancelled: { color: 'var(--text-muted)', label: 'Cancelled' },
    rejected: { color: 'var(--down)', label: 'Rejected' },
  };
  const s = map[status] || { color: 'var(--text-muted)', label: status };
  return <span style={{ color: s.color, fontWeight: 600, fontSize: '0.75rem' }}>{s.label}</span>;
}

type ActionState = { type: 'success' | 'error'; message: string } | null;

function OrderRow({ order, onApprove, onReject }: { order: Order; onApprove: (id: string) => void; onReject: (id: string) => void }) {
  const [confirming, setConfirming] = useState(false);

  return (
    <div className="order-row">
      <div className="order-info">
        <span className={`order-side ${order.side}`}>{order.side.toUpperCase()}</span>
        <span className="order-sym">{order.symbol}</span>
        <span className="order-qty">{order.qty} shares</span>
        {order.limitPrice && <span className="order-price">@ ${order.limitPrice.toFixed(2)}</span>}
      </div>
      <div className="order-meta">
        <span className="order-time"><Clock size={14} /> {fmtTime(order.createdAt)}</span>
        <StatusBadge status={order.status} />
      </div>
      <div className="order-actions">
        {confirming ? (
          <div className="confirm-btns">
            <button className="btn-approve" onClick={() => { onApprove(order.id); setConfirming(false); }}>Confirm</button>
            <button className="btn-reject" onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        ) : (
          <>
            <button className="btn-approve" onClick={() => setConfirming(true)}><CheckCircle size={16} /> Approve</button>
            <button className="btn-reject" onClick={() => onReject(order.id)}><XCircle size={16} /> Reject</button>
          </>
        )}
      </div>
    </div>
  );
}

export default function Approvals() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionState, setActionState] = useState<ActionState>(null);

  const loadOrders = useCallback(() => {
    fetch('/api/orders')
      .then(r => r.json())
      .then(data => { setOrders(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadOrders();
    const id = setInterval(loadOrders, 30000);
    return () => clearInterval(id);
  }, [loadOrders]);

  const handleApprove = async (id: string) => {
    try {
      const res = await fetch(`/api/order/${id}/approve`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'error') {
        setActionState({ type: 'error', message: data.message || 'Failed to approve' });
      } else {
        setActionState({ type: 'success', message: `${data.symbol || 'Order'} approved & submitted` });
      }
    } catch (e) {
      setActionState({ type: 'error', message: 'Network error' });
    }
    setTimeout(() => setActionState(null), 3000);
    loadOrders();
  };

  const handleReject = async (id: string) => {
    try {
      const res = await fetch(`/api/order/${id}/reject`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'error') {
        setActionState({ type: 'error', message: data.message || 'Failed to reject' });
      } else {
        setActionState({ type: 'success', message: 'Order rejected' });
      }
    } catch (e) {
      setActionState({ type: 'error', message: 'Network error' });
    }
    setTimeout(() => setActionState(null), 3000);
    loadOrders();
  };

  const pending = orders.filter(o => ['accepted', 'new', 'partially_filled', 'pending'].includes(o.status));
  const history = orders.filter(o => !['accepted', 'new', 'partially_filled', 'pending'].includes(o.status));

  return (
    <div className="page">
      <h1>Trade Approvals</h1>
      {actionState && (
        <div style={{
          padding: '0.6rem 1rem', borderRadius: 8, marginBottom: '1rem',
          background: actionState.type === 'success' ? 'var(--up-soft)' : 'var(--down-soft)',
          color: actionState.type === 'success' ? 'var(--up)' : 'var(--down)',
          fontWeight: 600, fontSize: '0.85rem',
          border: `1px solid ${actionState.type === 'success' ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
        }}>
          {actionState.type === 'success' ? '✓' : '✗'} {actionState.message}
        </div>
      )}
      {loading ? (
        <div className="card"><div className="empty-state"><p>Loading…</p></div></div>
      ) : pending.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <CheckCircle size={48} />
            <p>No pending orders — all clear!</p>
          </div>
        </div>
      ) : (
        <div className="card">
          <h3>Pending Orders ({pending.length})</h3>
          {pending.map(o => <OrderRow key={o.id} order={o} onApprove={handleApprove} onReject={handleReject} />)}
        </div>
      )}

      <div className="card" style={{ marginTop: '1rem' }}>
        <h3>Order History ({history.length})</h3>
        {history.length === 0 ? (
          <div className="empty-state"><p>No completed orders yet</p></div>
        ) : (
          <table className="history-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Limit</th>
                <th>Status</th>
                <th>Created</th>
                <th>Filled</th>
              </tr>
            </thead>
            <tbody>
              {history.map(o => (
                <tr key={o.id}>
                  <td className="sym">{o.symbol}</td>
                  <td><span className={`order-side ${o.side}`}>{o.side.toUpperCase()}</span></td>
                  <td>{o.qty}</td>
                  <td>{o.limitPrice ? `$${o.limitPrice.toFixed(2)}` : 'MKT'}</td>
                  <td><StatusBadge status={o.status} /></td>
                  <td>{fmtTime(o.createdAt)}</td>
                  <td>{o.filledAt ? fmtTime(o.filledAt) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
