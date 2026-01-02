export type UserRole = 'USER' | 'ADMIN';
export type UserStatus = 'ACTIVE' | 'DISABLED';

export interface UserProfile {
  id: string; // UUID (Primary Key, maps to Supabase auth user)
  first_name: string;
  last_name: string;
  email: string; // unique
  phone?: string;
  occupation?: string;
  role: UserRole;
  status: UserStatus;
  created_at: string; // TIMESTAMP
}

export interface StockData {
  id: string;
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  high: number;
  low: number;
  volume: number;
  marketCap: string;
  description: string;
}
