import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';

@Component({
  selector: 'app-pricing-page',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="glass-panel rounded-[30px] p-6 md:p-8">
      <p class="font-display text-sm uppercase tracking-[0.32em] text-slate-500">Pricing</p>
      <h2 class="mt-3 font-display text-4xl font-semibold text-slate-900">Subscription tiers built for modern investing workflows.</h2>

      <div class="mt-8 grid gap-4 xl:grid-cols-3">
        <article *ngFor="let tier of tiers" class="rounded-[28px] border p-6" [ngClass]="tier.highlight ? 'border-teal-300 bg-teal-50' : 'border-slate-200 bg-white/90'">
          <p class="text-xs uppercase tracking-[0.28em] text-slate-500">{{ tier.name }}</p>
          <h3 class="mt-3 text-3xl font-bold text-slate-900">{{ tier.price }}</h3>
          <p class="mt-2 text-sm leading-6 text-slate-600">{{ tier.description }}</p>
          <ul class="mt-6 space-y-3 text-sm text-slate-700">
            <li *ngFor="let feature of tier.features">• {{ feature }}</li>
          </ul>
        </article>
      </div>
    </section>
  `
})
export class PricingPageComponent {
  protected readonly tiers = [
    {
      name: 'FREE',
      price: '₹0',
      description: 'A delayed but polished intelligence feed for exploration and upgrade conversion.',
      features: ['Top 5 stocks', '24h delay', 'No indicators', 'Upgrade CTAs'],
      highlight: false
    },
    {
      name: 'PRO',
      price: '₹499/mo',
      description: 'The daily operator tier with real-time Telegram alerts and deeper technical context.',
      features: ['Top 20 stocks', 'Real-time alerts', 'RSI / MACD indicators', 'Ad-free workspace'],
      highlight: true
    },
    {
      name: 'ELITE',
      price: '₹1,499/mo',
      description: 'Full-spectrum research and administrative delegation for power users and internal desks.',
      features: ['Full market universe', 'Backtesting engine', 'Portfolio audit', 'Delegation rights'],
      highlight: false
    }
  ];
}
