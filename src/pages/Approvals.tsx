import { useState, useEffect, useCallback } from 'react';
import { CheckCircle, XCircle, Clock } from 'lucide-react';
import type { Order } from '../types';

function OrderRow({ order, onApprove, onReject }: { order: Order; onApprove: (id: string) => void; onReject: (id: string) => void }) {
  const [confirming, setConfirming] = useState(false);

  if (order.status === 'filled' || order.status === 'cancelled') return null;

  return (
    <div className="order-row">
      <div className="order-info">
        <span className={`order-side ${order.side}`}>{order.side.toUpperCase()}</span>
        <span className="order-sym">{order.symbol}</span>
        <span className="order-qty">{order.qty} shares</span>
        {order.limitPrice && <span className="order-price">@ ${order.limitPrice}</span>}
      </div>
      <div className="order-meta">
        <span className="order-time"><Clock size={14} /> {new Date(order.createdAt).toLocaleString()}</span>
        <span className={`order-status ${order.status}`}>{order.status}</span>
      </div>
      <div className="order-actions">
        {confirming ? (
          <div className="confirm-btns">
            <button className="btn-approve" onClick={() => { onApprove(order.id); setConfirming(false); }}>Confirm?</button>
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

  const loadOrders = useCallback(() => {
    fetch('/api/orders')
      .then(r => r.json())
      .then(data => { setOrders(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => { loadOrders(); }, [loadOrders]);

  const handleApprove = async (id: string) => {
    await fetch(`/api/order/${id}/approve`, { method: 'POST' });
    loadOrders();
  };

  const handleReject = async (id: string) => {
    await fetch(`/api/order/${id}/reject`, { method: 'POST' });
    loadOrders();
  };

  const pending = orders.filter(o => o.status === 'pending');

  return (
    <div className="page">
      <h1>Trade Approvals</h1>
      {loading ? (
        <div className="empty-state"><p>Loading...</p></div>
      ) : pending.length === 0 ? (
        <div className="empty-state">
          <CheckCircle size={48} />
          <p>No pending orders — all clear!</p>
        </div>
      ) : (
        <div className="card">
          <h3>Pending Orders ({pending.length})</h3>
          {pending.map(o => <OrderRow key={o.id} order={o} onApprove={handleApprove} onReject={handleReject} />)}
        </div>
      )}
      <div className="card" style={{ marginTop: '1rem' }}>
        <h3>Order History</h3>
        <div className="order-row header-row">
          <span>Symbol</span><span>Side</span><span>Qty</span><span>Status</span><span>Filled</span>
        </div>
        {orders.map(o => (
          <div key={o.id} className="order-row history-row">
            <span className="order-sym">{o.symbol}</span>
            <span className={`order-side ${o.side}`}>{o.side.toUpperCase()}</span>
            <span>{o.qty}</span>
            <span className={`order-status ${o.status}`}>{o.status}</span>
            <span>{o.filledAt ? new Date(o.filledAt).toLocaleString() : '—'}</span>
          </div>
        ))}
      </div>
    </div>
  );
}