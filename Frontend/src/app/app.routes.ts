import { Routes } from '@angular/router';

import { DashboardShellComponent } from './layout/dashboard-shell.component';
import { HomeDashboardComponent } from './pages/home-dashboard.component';
import { LoginPageComponent } from './pages/login-page.component';
import { PricingPageComponent } from './pages/pricing-page.component';
import { ProfilePageComponent } from './pages/profile-page.component';

export const routes: Routes = [
  {
    path: '',
    component: DashboardShellComponent,
    children: [
      { path: '', component: HomeDashboardComponent },
      { path: 'pricing', component: PricingPageComponent },
      { path: 'profile', component: ProfilePageComponent }
    ]
  },
  { path: 'login', component: LoginPageComponent }
];
