import { CommonModule } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

import { AuthService } from '../core/services/auth.service';
import { NavigationService } from '../core/services/navigation.service';

@Component({
  selector: 'app-dashboard-shell',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterOutlet],
  template: `
    <div class="min-h-screen p-4 md:p-6">
      <div class="mx-auto grid max-w-7xl gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside class="glass-panel rounded-[28px] p-5">
          <div class="mb-8">
            <p class="font-display text-sm uppercase tracking-[0.3em] text-slate-500">Anveshq</p>
            <h1 class="mt-3 font-display text-3xl font-semibold text-slate-900">Market Intelligence</h1>
            <p class="mt-3 text-sm leading-6 text-slate-600">
              Tier-aware intelligence for modern wealth desks, premium subscribers, and delegated admins.
            </p>
          </div>

          <div class="rounded-3xl bg-slate-950 px-4 py-5 text-slate-50">
            <p class="text-xs uppercase tracking-[0.28em] text-teal-200">Current Access</p>
            <ng-container *ngIf="auth.user() as user; else guestCard">
              <h2 class="mt-2 text-xl font-bold">{{ user.current_tier | uppercase }} / {{ user.role | uppercase }}</h2>
              <p class="mt-2 text-sm text-slate-300">{{ user.email }}</p>
            </ng-container>
            <ng-template #guestCard>
              <h2 class="mt-2 text-xl font-bold">Guest Mode</h2>
              <p class="mt-2 text-sm text-slate-300">Explore the UI, then sign in or load a demo tier.</p>
            </ng-template>
            <div class="mt-4 flex flex-wrap gap-2">
              <button class="rounded-full bg-teal-500 px-3 py-2 text-xs font-semibold text-slate-950" (click)="auth.loadDemoSession('user', 'pro')">
                Demo PRO
              </button>
              <button class="rounded-full bg-orange-400 px-3 py-2 text-xs font-semibold text-slate-950" (click)="auth.loadDemoSession('admin', 'elite')">
                Demo ELITE Admin
              </button>
            </div>
          </div>

          <nav class="mt-8 space-y-2">
            <a
              *ngFor="let item of navItems()"
              [routerLink]="item.route"
              class="flex items-center justify-between rounded-2xl border border-slate-200/70 px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-teal-400 hover:bg-teal-50 hover:text-teal-900"
            >
              <span>{{ item.label }}</span>
              <span *ngIf="item.badge" class="rounded-full bg-slate-100 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-slate-500">
                {{ item.badge }}
              </span>
            </a>
          </nav>
        </aside>

        <main class="space-y-6">
          <router-outlet></router-outlet>
        </main>
      </div>
    </div>
  `
})
export class DashboardShellComponent {
  protected readonly auth = inject(AuthService);
  private readonly navigation = inject(NavigationService);

  protected readonly navItems = computed(() => this.navigation.getNavigation(this.auth.user()));
}
