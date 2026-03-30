import { CommonModule } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AuthService } from '../core/services/auth.service';

@Component({
  selector: 'app-profile-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="glass-panel rounded-[30px] p-6 md:p-8">
      <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p class="font-display text-sm uppercase tracking-[0.32em] text-slate-500">Profile</p>
          <h2 class="mt-3 font-display text-4xl font-semibold text-slate-900">Subscription and alert delivery controls.</h2>
        </div>
        <button class="rounded-2xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700" (click)="auth.logout()">Sign Out</button>
      </div>

      <div *ngIf="auth.user() as user; else guestState" class="mt-8 grid gap-4 xl:grid-cols-[1fr_0.8fr]">
        <div class="rounded-[26px] border border-slate-200 bg-white/90 p-6">
          <h3 class="text-xl font-bold text-slate-900">{{ user.email }}</h3>
          <p class="mt-2 text-sm text-slate-600">Role: {{ user.role | uppercase }} | Tier: {{ user.current_tier | uppercase }}</p>
          <p class="mt-2 text-sm text-slate-600">Expiry: {{ user.subscription_expiry || 'Active / demo session' }}</p>
        </div>

        <form class="rounded-[26px] border border-slate-200 bg-white/90 p-6" (ngSubmit)="saveTelegram()">
          <label class="mb-2 block text-sm font-semibold text-slate-700">Telegram Chat ID</label>
          <input [(ngModel)]="telegramChatId" name="telegramChatId" class="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-teal-500" />
          <button class="mt-4 rounded-2xl bg-teal-600 px-4 py-3 text-sm font-semibold text-white" type="submit">Save Telegram Integration</button>
          <p *ngIf="saveMessage" class="mt-3 text-sm text-slate-600">{{ saveMessage }}</p>
        </form>
      </div>

      <ng-template #guestState>
        <div class="mt-8 rounded-[26px] border border-dashed border-slate-300 bg-white/70 p-6 text-sm text-slate-600">
          Sign in or load a demo session to manage subscription metadata and Telegram delivery.
        </div>
      </ng-template>
    </section>
  `
})
export class ProfilePageComponent {
  protected readonly auth = inject(AuthService);
  protected telegramChatId = '';
  protected saveMessage = '';

  protected readonly currentUser = computed(() => this.auth.user());

  protected saveTelegram(): void {
    this.auth.updateTelegramChatId(this.telegramChatId || null).subscribe({
      next: () => {
        this.saveMessage = 'Telegram integration updated.';
      },
      error: () => {
        this.saveMessage = 'The backend profile endpoint is ready. Start the API locally to persist this change.';
      }
    });
  }
}
