import React from 'react';
import { useNavigate } from 'react-router-dom';

export const HomePage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div>
      {/* Hero Section */}
      <section style={{
        background: 'linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%)',
        color: 'white',
        paddingTop: 'var(--spacing-3xl)',
        paddingBottom: 'var(--spacing-3xl)',
        textAlign: 'center'
      }}>
        <div className="container">
          <h1 style={{ color: 'white', fontSize: '3rem' }}>Welcome to StockList</h1>
          <p style={{ fontSize: '1.25rem', marginBottom: 'var(--spacing-2xl)', color: '#e0f2fe' }}>
            Your professional stock market management platform
          </p>
          <button className="btn btn-lg" style={{ background: 'white', color: 'var(--primary)' }} onClick={() => navigate('/signup')}>
            Get Started
          </button>
        </div>
      </section>

      {/* Features Section */}
      <section style={{ paddingTop: 'var(--spacing-3xl)', paddingBottom: 'var(--spacing-3xl)', background: 'var(--bg-light)' }}>
        <div className="container">
          <h2 style={{ textAlign: 'center', marginBottom: 'var(--spacing-2xl)' }}>Why Choose StockList?</h2>
          <div className="grid grid-3">
            <div className="card">
              <h4>Real-time Data</h4>
              <p>Access live stock prices and market data updated in real-time.</p>
            </div>
            <div className="card">
              <h4>Advanced Analytics</h4>
              <p>Powerful charts and analysis tools for informed decisions.</p>
            </div>
            <div className="card">
              <h4>Portfolio Management</h4>
              <p>Track and manage your investments in one place.</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};