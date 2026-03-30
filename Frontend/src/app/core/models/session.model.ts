export type UserRole = 'super_admin' | 'admin' | 'user';
export type SubscriptionTier = 'free' | 'pro' | 'elite';

export interface UserSessionProfile {
  id: number;
  email: string;
  role: UserRole;
  current_tier: SubscriptionTier;
  telegram_chat_id?: string | null;
  subscription_expiry?: string | null;
}

export interface AuthSession {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: UserSessionProfile;
}

export interface NavigationItem {
  label: string;
  route: string;
  badge?: string;
}
