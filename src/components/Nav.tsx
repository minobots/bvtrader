import { TrendingUp, BarChart3, CheckCircle, Eye, BookOpen } from 'lucide-react';
import type { Page } from '../App';

const navItems: { id: Page; label: string; icon: React.ReactNode }[] = [
  { id: 'portfolio', label: 'Portfolio', icon: <TrendingUp size={16} /> },
  { id: 'analysis',  label: 'Analysis',  icon: <BarChart3 size={16} /> },
  { id: 'approvals', label: 'Approvals', icon: <CheckCircle size={16} /> },
  { id: 'market',    label: 'Watch',     icon: <Eye size={16} /> },
  { id: 'library',   label: 'Library',   icon: <BookOpen size={16} /> },
];

export default function Nav({ current, onNavigate }: { current: Page; onNavigate: (p: Page) => void }) {
  return (
    <nav className="nav">
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
