import { TrendingUp, BarChart3, CheckCircle, Eye, BookOpen } from 'lucide-react';
import type { Page } from '../App';

const navItems: { id: Page; label: string; icon: React.ReactNode }[] = [
  { id: 'portfolio', label: 'Portfolio', icon: <TrendingUp size={18} /> },
  { id: 'analysis',  label: 'Analysis',  icon: <BarChart3 size={18} /> },
  { id: 'approvals', label: 'Approvals', icon: <CheckCircle size={18} /> },
  { id: 'market',    label: 'Watch',     icon: <Eye size={18} /> },
  { id: 'library',   label: 'Library',   icon: <BookOpen size={18} /> },
];

export default function Nav({ current, onNavigate }: { current: Page; onNavigate: (p: Page) => void }) {
  return (
    <nav className="nav">
      <div className="nav-brand">Wealth</div>
      <div className="nav-links">
        {navItems.map(item => (
          <button
            key={item.id}
            className={`nav-btn ${current === item.id ? 'active' : ''}`}
            onClick={() => onNavigate(item.id)}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}