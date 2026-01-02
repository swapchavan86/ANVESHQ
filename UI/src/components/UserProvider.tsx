import React, { useState, useEffect } from 'react';
import { UserContext, type UserContextType } from '../utils/user';
import { authService } from '../services/authService';
import type { UserProfile } from '../utils/types';
import * as SupabaseTypes from '@supabase/supabase-js';
import { supabase } from '../services/supabaseClient';

interface UserProviderProps {
  children: React.ReactNode;
}

export const UserProvider: React.FC<UserProviderProps> = ({ children }) => {
  const [user, setUser] = useState<SupabaseTypes.User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const checkUser = async () => {
      try {
        const result = await authService.getCurrentUser();
        if (result) {
          setUser(result.user);
          setProfile(result.profile);
        }
      } catch (error) {
        console.error('Error checking user:', error);
      } finally {
        setLoading(false);
      }
    };

    // Check initial auth state
    checkUser();

    // Subscribe to auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event, session) => {
        if (session?.user) {
          setUser(session.user);
          
          // Create profile if it doesn't exist
          await authService.createProfileIfNotExists(session.user);
          
          const profile = await authService.getUserProfile(session.user.id);
          setProfile(profile);
        } else {
          setUser(null);
          setProfile(null);
        }
      }
    );

    return () => {
      subscription?.unsubscribe();
    };
  }, []);

  const signIn = async (email: string, password: string) => {
    const result = await authService.signIn(email, password);
    setUser(result.user);
    setProfile(result.profile);
    return result;
  };

  const signOut = async () => {
    await authService.signOut();
    setUser(null);
    setProfile(null);
  };

  const signUp = async (
    email: string,
    password: string,
    firstName: string,
    lastName: string,
    phone?: string
  ) => {
    return await authService.signUp(email, password, firstName, lastName, phone);
  };

  const verifyOtp = async (email: string, token: string, type: 'email' | 'sms') => {
    return await authService.verifyOtp(email, token, type);
  };

  const value: UserContextType = {
    user,
    profile,
    loading,
    signIn,
    signOut,
    signUp,
    verifyOtp,
  };

  return (
    <UserContext.Provider value={value}>
      {children}
    </UserContext.Provider>
  );
};