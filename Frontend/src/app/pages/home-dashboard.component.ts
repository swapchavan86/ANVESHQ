import { CommonModule } from '@angular/common';
import { Component, computed, inject } from '@angular/core';

import { AuthService } from '../core/services/auth.service';

@Component({
  selector: 'app-home-dashboard',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="glass-panel rounded-[30px] p-6 md:p-8">
      <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p class="font-display text-sm uppercase tracking-[0.32em] text-slate-500">Dashboard</p>
          <h2 class="mt-3 font-display text-4xl font-semibold text-slate-900">Wealth-tech intelligence that adapts to every tier.</h2>
        </div>
        <div class="rounded-3xl border border-teal-200 bg-teal-50 px-5 py-4 text-sm text-teal-950">
          <p class="font-semibold">Legacy cron safe</p>
          <p class="mt-1 text-teal-900/80">The market engine keeps running without any user session dependency.</p>
        </div>
      </div>

      <div class="mt-8 grid gap-4 md:grid-cols-3">
        <article *ngFor="let card of cards()" class="rounded-[26px] border border-slate-200 bg-white/90 p-5">
          <p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">{{ card.eyebrow }}</p>
          <h3 class="mt-3 text-2xl font-bold text-slate-900">{{ card.title }}</h3>
          <p class="mt-3 text-sm leading-6 text-slate-600">{{ card.copy }}</p>
        </article>
      </div>

      <div class="mt-8 grid gap-4 lg:grid-cols-2">
        <div id="technicals" class="rounded-[26px] bg-slate-950 p-6 text-slate-50">
          <p class="text-xs uppercase tracking-[0.3em] text-teal-200">Technical Suite</p>
          <h3 class="mt-3 text-2xl font-bold">RSI, MACD, and premium chart context</h3>
          <p class="mt-3 text-sm leading-6 text-slate-300">
            PRO and ELITE users unlock technical signal overlays directly from the new FastAPI premium endpoints.
          </p>
        </div>
        <div id="backtest" class="rounded-[26px] bg-orange-50 p-6 text-slate-900">
          <p class="text-xs uppercase tracking-[0.3em] text-orange-500">Elite Research</p>
          <h3 class="mt-3 text-2xl font-bold">Backtesting and portfolio audit workflows</h3>
          <p class="mt-3 text-sm leading-6 text-slate-600">
            ELITE users get strategy validation, audit tooling, and delegated admin collaboration paths.
          </p>
        </div>
      </div>
    </section>
  `
})
export class HomeDashboardComponent {
  private readonly auth = inject(AuthService);

  protected readonly cards = computed(() => {
    const user = this.auth.user();
    const tier = user?.current_tier ?? 'free';
    return [
      {
        eyebrow: 'Tier Logic',
        title: tier === 'free' ? 'Top 5 with 24h delay' : tier === 'pro' ? 'Top 20 and real-time alerts' : 'Full universe access',
        copy: 'The interface mirrors the backend tier guard rules, so what users see matches what the API allows.'
      },
      {
        eyebrow: 'Admin Delegation',
        title: user?.role === 'admin' || user?.role === 'super_admin' ? 'Delegation tools enabled' : 'Upgrade into managed access',
        copy: 'Admins can create delegated accounts, review user inventory, and safely extend access across a team.'
      },
      {
        eyebrow: 'Performance',
        title: 'Cached intelligence endpoint',
        copy: 'The `/stocks/top` feed is cached in memory to keep premium dashboards responsive during heavy traffic.'
      }
    ];
  });
}
