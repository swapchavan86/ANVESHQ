import { createContext, useContext } from 'react';
import type { UserProfile } from './types';
import * as SupabaseTypes from '@supabase/supabase-js';

export interface UserContextType {
  user: SupabaseTypes.User | null;
  profile: UserProfile | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<any>;
  signOut: () => Promise<void>;
  signUp: (email: string, password: string, firstName: string, lastName: string, phone?: string) => Promise<any>;
  verifyOtp: (email: string, token: string, type: 'email' | 'sms') => Promise<any>;
}

export const UserContext = createContext<UserContextType | undefined>(undefined);

export const useUser = () => {
  const context = useContext(UserContext);
  if (context === undefined) {
    throw new Error('useUser must be used within a UserProvider');
  }
  return context;
};