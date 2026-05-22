import { useState } from 'react';
import Portfolio from './pages/Portfolio';
import Analysis from './pages/Analysis';
import Approvals from './pages/Approvals';
import MarketWatch from './pages/MarketWatch';
import Library from './pages/Library';
import Nav from './components/Nav';
import './App.css';

type Page = 'portfolio' | 'analysis' | 'approvals' | 'market' | 'library';

export default function App() {
  const [page, setPage] = useState<Page>('portfolio');

  return (
    <div className="app">
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