import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { tap } from 'rxjs';

import { AuthSession, SubscriptionTier, UserRole } from '../models/session.model';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly storageKey = 'anveshq.session';
  private readonly apiBase = 'http://localhost:8000/api';
  private readonly sessionState = signal<AuthSession | null>(this.readStoredSession());

  readonly session = computed(() => this.sessionState());
  readonly user = computed(() => this.sessionState()?.user ?? null);
  readonly isAuthenticated = computed(() => !!this.sessionState()?.access_token);

  login(email: string, password: string) {
    return this.http
      .post<AuthSession>(`${this.apiBase}/auth/login`, { email, password })
      .pipe(tap((session) => this.persistSession(session)));
  }

  register(email: string, password: string) {
    return this.http
      .post<AuthSession>(`${this.apiBase}/auth/register`, { email, password })
      .pipe(tap((session) => this.persistSession(session)));
  }

  updateTelegramChatId(telegram_chat_id: string | null) {
    return this.http
      .patch<AuthSession['user']>(
        `${this.apiBase}/auth/me/telegram`,
        { telegram_chat_id },
        { headers: this.authHeaders() }
      )
      .pipe(
        tap((user) => {
          const currentSession = this.sessionState();
          if (currentSession) {
            this.persistSession({ ...currentSession, user });
          }
        })
      );
  }

  logout(): void {
    localStorage.removeItem(this.storageKey);
    this.sessionState.set(null);
  }

  loadDemoSession(role: UserRole, tier: SubscriptionTier): void {
    this.persistSession({
      access_token: 'demo-token',
      token_type: 'bearer',
      expires_at: new Date(Date.now() + 3600_000).toISOString(),
      user: {
        id: 1,
        email: `${tier}.${role}@demo.anveshq.ai`,
        role,
        current_tier: tier,
        telegram_chat_id: tier === 'free' ? null : '@anveshq_demo'
      }
    });
  }

  private authHeaders() {
    const token = this.sessionState()?.access_token ?? '';
    return { Authorization: `Bearer ${token}` };
  }

  private persistSession(session: AuthSession): void {
    localStorage.setItem(this.storageKey, JSON.stringify(session));
    this.sessionState.set(session);
  }

  private readStoredSession(): AuthSession | null {
    const rawValue = localStorage.getItem(this.storageKey);
    if (!rawValue) {
      return null;
    }

    try {
      return JSON.parse(rawValue) as AuthSession;
    } catch {
      localStorage.removeItem(this.storageKey);
      return null;
    }
  }
}
