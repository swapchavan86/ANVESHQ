import { supabase } from './supabaseClient';
import type { UserProfile } from '../utils/types';
import * as SupabaseTypes from '@supabase/supabase-js';

export interface AuthResponseData {
  user: SupabaseTypes.User | null;
  session: SupabaseTypes.Session | null;
}

interface UserAuthResult {
  user: SupabaseTypes.User;
  profile: UserProfile | null;
}

export const authService = {
  async signUp(
    email: string,
    password: string,
    firstName: string,
    lastName: string,
    phone?: string
  ): Promise<AuthResponseData> {
    try {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          data: {
            first_name: firstName,
            last_name: lastName,
            phone: phone || null,
          },
        },
      });

      if (error) throw error;

      // Create user profile in users table
      if (data.user) {
        const profileData = {
          id: data.user.id,
          email: data.user.email || email,
          first_name: firstName,
          last_name: lastName,
          phone: phone || null,
          role: 'user' as const,
          status: 'active' as const,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };

        const { error: profileError } = await supabase
          .from('users')
          .insert([profileData]);

        if (profileError) {
          console.error('Error creating user profile:', profileError);
          // Don't throw - user auth was successful
        }
      }

      return data;
    } catch (error) {
      console.error('Sign up error:', error);
      throw error;
    }
  },

  async verifyOtp(
    email: string,
    token: string,
    type: 'email' | 'sms'
  ): Promise<AuthResponseData> {
    try {
      if (type === 'email') {
        const { data, error } = await supabase.auth.verifyOtp({
          email,
          token,
          type: 'email',
        });

        if (error) throw error;
        return data;
      } else if (type === 'sms') {
        const { data, error } = await supabase.auth.verifyOtp({
          phone: email,
          token,
          type: 'sms',
        });

        if (error) throw error;
        return data;
      }

      throw new Error('Invalid OTP type');
    } catch (error) {
      console.error('OTP verification error:', error);
      throw error;
    }
  },

  async signIn(email: string, password: string): Promise<UserAuthResult> {
    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });

      if (error) throw error;

      if (data.user) {
        const profile = await this.getUserProfile(data.user.id);
        return { user: data.user, profile };
      }

      throw new Error('User data not found after sign in.');
    } catch (error) {
      console.error('Sign in error:', error);
      throw error;
    }
  },

  async signOut(): Promise<boolean> {
    try {
      const { error } = await supabase.auth.signOut();
      if (error) throw error; 
      return true; 
    } catch (error) {
      console.error('Sign out error:', error); 
      throw error; 
    }
  },

  async getUserProfile(userId: string): Promise<UserProfile | null> {
    try {
      const { data, error } = await supabase
        .from('users')
        .select('*')
        .eq('id', userId)
        .maybeSingle(); // Use maybeSingle instead of single to handle 0 rows gracefully

      if (error && error.code !== 'PGRST116') {
        console.error('Error fetching user profile:', error);
        return null;
      }

      if (!data) {
        console.warn(`No profile found for user ${userId}. User may have just signed up.`);
        return null;
      }

      return data as UserProfile;
    } catch (error) {
      console.error('Error in getUserProfile:', error);
      return null;
    }
  },

  async getCurrentUser(): Promise<UserAuthResult | null> {
    try {
      const { data: { user }, error } = await supabase.auth.getUser();

      if (error) {
        console.error('Error getting auth user:', error);
        return null;
      }

      if (!user) {
        return null;
      }

      // Try to fetch profile, but don't fail if it doesn't exist yet
      let profile: UserProfile | null = null;
      try {
        profile = await this.getUserProfile(user.id);
      } catch (err) {
        console.warn('Could not fetch user profile:', err);
      }

      return { user, profile };
    } catch (error) {
      console.error('Error in getCurrentUser:', error);
      return null;
    }
  },

  async updateUserProfile(
    userId: string,
    updates: Partial<UserProfile>
  ): Promise<UserProfile | null> {
    try {
      const { data, error } = await supabase
        .from('users')
        .update({
          ...updates,
          updated_at: new Date().toISOString(),
        })
        .eq('id', userId)
        .select()
        .maybeSingle();

      if (error) throw error;
      return data as UserProfile | null;
    } catch (error) {
      console.error('Error updating user profile:', error);
      throw error;
    }
  },

  // Create profile if it doesn't exist (helper method)
  async createProfileIfNotExists(user: SupabaseTypes.User): Promise<void> {
    try {
      const existing = await this.getUserProfile(user.id);
      if (existing) return;

      const { error } = await supabase.from('users').insert([
        {
          id: user.id,
          email: user.email,
          first_name: user.user_metadata?.first_name || '',
          last_name: user.user_metadata?.last_name || '',
          phone: user.user_metadata?.phone || null,
          role: 'user',
          status: 'active',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]);

      if (error) {
        console.error('Error creating user profile:', error);
      }
    } catch (error) {
      console.error('Error in createProfileIfNotExists:', error);
    }
  },
};