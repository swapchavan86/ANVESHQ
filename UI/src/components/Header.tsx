import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useUser } from '../utils/user';
import StockListLogo from '../assets/StockList.svg';

export const Header: React.FC = () => {
  const navigate = useNavigate();
  const { user, signOut } = useUser();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [searchSymbol, setSearchSymbol] = useState('');

  const handleSignOut = async () => {
    console.log('Attempting to sign out...');
    try {
      await signOut();
      console.log('Sign out successful. Navigating to /signin...');
      navigate('/signin');
    } catch (error) {
      console.error('Sign out error:', error);
    }
  };

  const handleNavClick = (path: string) => {
    navigate(path);
    setMobileMenuOpen(false);
  };

  const handleSearch = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && searchSymbol.trim() !== '') {
      navigate(`/stocks/${searchSymbol.trim().toUpperCase()}`);
      setSearchSymbol('');
      setMobileMenuOpen(false);
    }
  };

  const handleSearchClick = () => {
    if (searchSymbol.trim() !== '') {
      navigate(`/stocks/${searchSymbol.trim().toUpperCase()}`);
      setSearchSymbol('');
      setMobileMenuOpen(false);
    }
  };

  return (
    <header className="header">
      <div className="container">
        <div className="nav-container">
          {/* Logo */}
          <div className="logo" onClick={() => navigate('/')}>
            <img 
              src={StockListLogo} 
              alt="StockList Logo" 
              className="logo-image"
            />
          </div>

          {/* Navigation Links */}
          <nav className="nav-links" style={{ display: mobileMenuOpen ? 'flex' : 'flex' }}>
            <li><a href="/" onClick={() => handleNavClick('/')}>Home</a></li>
            <li><a href="/about" onClick={() => handleNavClick('/about')}>About</a></li>
            <li><a href="/contact" onClick={() => handleNavClick('/contact')}>Contact</a></li>
          </nav>

          {/* Stock Search */}
          <div className="search-container">
            <input
              type="text"
              placeholder="Search stock symbol..."
              className="search-input"
              value={searchSymbol}
              onChange={(e) => setSearchSymbol(e.target.value)}
              onKeyDown={handleSearch}
            />
            <button className="search-btn" onClick={handleSearchClick} aria-label="Search">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
            </button>
          </div>

          {/* Auth Buttons */}
          <div style={{ display: 'flex', gap: 'var(--spacing-md)', alignItems: 'center' }}>
            {user ? (
              <>
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  Welcome, {user.email?.split('@')[0]}
                </span>
                <button className="btn btn-sm btn-outline" onClick={handleSignOut}>
                  Sign Out
                </button>
              </>
            ) : (
              <>
                <button 
                  className="btn btn-sm btn-ghost"
                  onClick={() => navigate('/signin')}
                >
                  Sign In
                </button>
                <button 
                  className="btn btn-sm btn-primary"
                  onClick={() => navigate('/signup')}
                >
                  Sign Up
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};