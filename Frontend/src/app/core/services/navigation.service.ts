import { Injectable } from '@angular/core';

import { NavigationItem, UserSessionProfile } from '../models/session.model';

@Injectable({ providedIn: 'root' })
export class NavigationService {
  getNavigation(user: UserSessionProfile | null): NavigationItem[] {
    const items: NavigationItem[] = [
      { label: 'Market Pulse', route: '/' },
      { label: 'Pricing', route: '/pricing' }
    ];

    if (!user) {
      items.push({ label: 'Sign In', route: '/login' });
      return items;
    }

    items.push({ label: 'Profile', route: '/profile' });

    if (user.current_tier === 'free') {
      items.push({ label: 'Upgrade', route: '/pricing', badge: '24h Delay' });
    }

    if (user.current_tier === 'pro' || user.current_tier === 'elite') {
      items.push({ label: 'Advanced Charts', route: '/#technicals', badge: 'RSI / MACD' });
    }

    if (user.current_tier === 'elite') {
      items.push({ label: 'Backtesting', route: '/#backtest', badge: 'Elite' });
      items.push({ label: 'Portfolio Audit', route: '/#audit' });
    }

    if (user.role === 'admin' || user.role === 'super_admin') {
      items.push({ label: 'User Management', route: '/#admin-users', badge: 'Admin' });
      items.push({ label: 'System Logs', route: '/#system-logs' });
    }

    return items;
  }
}
