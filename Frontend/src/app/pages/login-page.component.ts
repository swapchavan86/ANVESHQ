import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService } from '../core/services/auth.service';

@Component({
  selector: 'app-login-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="flex min-h-screen items-center justify-center p-6">
      <section class="glass-panel w-full max-w-5xl rounded-[32px] p-6 md:grid md:grid-cols-[1.1fr_0.9fr] md:p-8">
        <div class="border-b border-slate-200 pb-6 md:border-b-0 md:border-r md:pb-0 md:pr-8">
          <p class="font-display text-sm uppercase tracking-[0.32em] text-slate-500">Access Portal</p>
          <h1 class="mt-3 font-display text-4xl font-semibold text-slate-900">Professional market intelligence for every subscription tier.</h1>
          <p class="mt-4 text-sm leading-7 text-slate-600">
            Sign in to unlock live alerts, backtesting, delegated administration, and profile-linked Telegram delivery.
          </p>
          <div class="mt-8 grid gap-3 sm:grid-cols-3">
            <button class="rounded-2xl bg-slate-950 px-4 py-3 text-sm font-semibold text-white" (click)="loadDemo('user', 'free')">Demo FREE</button>
            <button class="rounded-2xl bg-teal-600 px-4 py-3 text-sm font-semibold text-white" (click)="loadDemo('user', 'pro')">Demo PRO</button>
            <button class="rounded-2xl bg-orange-500 px-4 py-3 text-sm font-semibold text-white" (click)="loadDemo('admin', 'elite')">Demo ELITE</button>
          </div>
        </div>

        <div class="pt-6 md:pl-8 md:pt-0">
          <form class="space-y-4" (ngSubmit)="submitLogin()">
            <div>
              <label class="mb-2 block text-sm font-semibold text-slate-700">Email</label>
              <input [(ngModel)]="email" name="email" class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-teal-500" />
            </div>
            <div>
              <label class="mb-2 block text-sm font-semibold text-slate-700">Password</label>
              <input [(ngModel)]="password" type="password" name="password" class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-teal-500" />
            </div>
            <button class="w-full rounded-2xl bg-teal-600 px-4 py-3 text-sm font-semibold text-white" type="submit">Sign In</button>
            <button class="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700" type="button" (click)="submitRegister()">Create Account</button>
            <p *ngIf="statusMessage" class="text-sm text-slate-600">{{ statusMessage }}</p>
          </form>
        </div>
      </section>
    </div>
  `
})
export class LoginPageComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected email = '';
  protected password = '';
  protected statusMessage = '';

  protected submitLogin(): void {
    this.auth.login(this.email, this.password).subscribe({
      next: () => this.router.navigateByUrl('/'),
      error: () => {
        this.statusMessage = 'Backend login is unavailable right now, so you can use the demo tier buttons above.';
      }
    });
  }

  protected submitRegister(): void {
    this.auth.register(this.email, this.password).subscribe({
      next: () => this.router.navigateByUrl('/'),
      error: () => {
        this.statusMessage = 'Registration endpoint is ready on the backend. Run the API locally to complete signup.';
      }
    });
  }

  protected loadDemo(role: 'admin' | 'user', tier: 'free' | 'pro' | 'elite'): void {
    this.auth.loadDemoSession(role, tier);
    void this.router.navigateByUrl('/');
  }
}
