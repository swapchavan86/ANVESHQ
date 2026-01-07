import React from 'react';
import Link from 'next/link';

export const MainLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <div className="flex flex-col min-h-screen bg-background text-foreground font-sans">
      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b border-border bg-white/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <Link href="/" className="text-2xl font-bold tracking-tighter text-foreground">
              ANVESHQ<span className="text-accent-success">.</span>
            </Link>
            <nav className="hidden md:flex items-center space-x-1">
              <NavItem href="/market" label="Market Overview" />
              <NavItem href="/watchlist" label="Watchlist" />
            </nav>
          </div>
          <div className="flex items-center gap-4">
            {/* Placeholder for Search or User Profile */}
            <div className="h-8 w-8 rounded-full bg-secondary" />
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 py-8 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">{children}</div>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-white py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6">
          <p className="text-xs text-gray-400">© 2024 Anveshq Intelligence. All rights reserved.</p>
          <nav className="flex flex-wrap justify-center gap-x-8 gap-y-2 text-xs font-medium text-gray-500">
            <Link href="/about" className="hover:text-foreground transition-colors">About Us</Link>
            <Link href="/contact" className="hover:text-foreground transition-colors">Contact Us</Link>
            <Link href="/privacy" className="hover:text-foreground transition-colors">Privacy Policy</Link>
            <Link href="/terms" className="hover:text-foreground transition-colors">Terms of Use</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
};

const NavItem = ({ href, label }: { href: string; label: string }) => (
  <Link href={href} className="px-4 py-2 text-sm font-medium rounded-md hover:bg-secondary transition-colors text-gray-600 hover:text-foreground">
    {label}
  </Link>
);