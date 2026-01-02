import React from 'react';

export const Footer: React.FC = () => {
  const currentYear = new Date().getFullYear();

  return (
    <footer style={{
      background: 'var(--secondary)',
      color: 'white',
      marginTop: 'var(--spacing-3xl)',
      paddingTop: 'var(--spacing-3xl)',
      paddingBottom: 'var(--spacing-2xl)'
    }}>
      <div className="container">
        <div className="grid grid-3" style={{ marginBottom: 'var(--spacing-3xl)' }}>
          {/* Company Info */}
          <div>
            <h4 style={{ color: 'white', marginBottom: 'var(--spacing-lg)' }}>StockList</h4>
            <p style={{ color: '#cbd5e1', marginBottom: 'var(--spacing-md)' }}>
              Professional stock market management and analysis platform.
            </p>
          </div>

          {/* Quick Links */}
          <div>
            <h5 style={{ color: 'white', marginBottom: 'var(--spacing-lg)' }}>Quick Links</h5>
            <ul style={{ listStyle: 'none' }}>
              <li><a href="/" style={{ color: '#cbd5e1' }}>Home</a></li>
              <li><a href="/stocks" style={{ color: '#cbd5e1' }}>Stocks</a></li>
              <li><a href="/about" style={{ color: '#cbd5e1' }}>About Us</a></li>
              <li><a href="/contact" style={{ color: '#cbd5e1' }}>Contact</a></li>
            </ul>
          </div>

          {/* Contact Info */}
          <div>
            <h5 style={{ color: 'white', marginBottom: 'var(--spacing-lg)' }}>Contact</h5>
            <p style={{ color: '#cbd5e1', marginBottom: 'var(--spacing-md)' }}>
              Email: info@stocklist.com<br />
              Phone: +1 (555) 123-4567<br />
              Address: 123 Finance St, NY 10001
            </p>
          </div>
        </div>

        <div className="divider" style={{ borderColor: '#334155' }}></div>

        {/* Copyright */}
        <div style={{
          textAlign: 'center',
          color: '#cbd5e1',
          fontSize: '0.875rem'
        }}>
          <p>&copy; {currentYear} StockList. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
};