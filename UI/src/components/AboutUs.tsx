import React from 'react';

export const AboutUs: React.FC = () => {
  return (
    <div className="container" style={{ paddingTop: 'var(--spacing-3xl)', paddingBottom: 'var(--spacing-3xl)' }}>
      <h1>About Us</h1>
      
      <div className="grid grid-2" style={{ marginTop: 'var(--spacing-2xl)', marginBottom: 'var(--spacing-2xl)' }}>
        <div>
          <h2>Our Mission</h2>
          <p>
            We empower investors with real-time market data, advanced analytics, and intuitive tools
            to make informed investment decisions.
          </p>
        </div>
        <div>
          <h2>Our Vision</h2>
          <p>
            To democratize stock market access and create a transparent, efficient platform for
            all investors worldwide.
          </p>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 'var(--spacing-2xl)' }}>
        <h3>Why Choose StockList?</h3>
        <ul style={{ listStyle: 'none', padding: 0 }}>
          <li style={{ padding: 'var(--spacing-md) 0', borderBottom: '1px solid var(--border-color)' }}>
            ✓ Real-time stock market data
          </li>
          <li style={{ padding: 'var(--spacing-md) 0', borderBottom: '1px solid var(--border-color)' }}>
            ✓ Advanced charting tools
          </li>
          <li style={{ padding: 'var(--spacing-md) 0', borderBottom: '1px solid var(--border-color)' }}>
            ✓ Portfolio management
          </li>
          <li style={{ padding: 'var(--spacing-md) 0' }}>
            ✓ 24/7 customer support
          </li>
        </ul>
      </div>
    </div>
  );
};