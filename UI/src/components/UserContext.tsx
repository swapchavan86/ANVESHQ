import React, { useState, useEffect, type ReactNode } from 'react';
import { authService, type AuthResponseData } from '../services/authService'; // Import AuthResponseData
import type { UserProfile } from '../utils/types';
import { UserContext, type UserContextType, type UserAuthResult } from '../utils/user';
import { supabase } from '../services/supabaseClient';
import type { User } from '@supabase/supabase-js';

export const UserProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchUser = async () => {
      try {
        setLoading(true);
        const currentUserData = await authService.getCurrentUser();
        setUser(currentUserData?.user || null);
        setProfile(currentUserData?.profile || null);
      } catch (error: unknown) {
        console.error('Failed to fetch current user:', error);
        setUser(null);
        setProfile(null);
      } finally {
        setLoading(false);
      }
    };

    fetchUser();

    const { data: authListener } = supabase.auth.onAuthStateChange(
      async (_event, session) => {
        if (session?.user) {
          const userProfile = await authService.getUserProfile(session.user.id);
          setUser(session.user);
          setProfile(userProfile);
        } else {
          setUser(null);
          setProfile(null);
        }
        setLoading(false);
      }
    );

    return () => {
      authListener?.subscription.unsubscribe();
    };
  }, []);

  const handleSignIn = async (email: string, password: string): Promise<{ user: User, profile: UserProfile | null }> => {
    setLoading(true);
    try {
      const { user: signedInUser, profile: signedInProfile } = await authService.signIn(email, password);
      setUser(signedInUser);
      setProfile(signedInProfile);
      return { user: signedInUser, profile: signedInProfile }; // Ensure this matches the return type of signIn
    } catch (error: Error) {
      console.error('Login failed:', error);
      throw error;
    } finally {
      setLoading(false);
    }
  };

  const handleSignOut = async () => {
    setLoading(true);
    try {
      await authService.signOut();
      setUser(null);
      setProfile(null); // Clear profile on sign out
    } catch (error: Error) {
      console.error('Logout failed:', error);
      throw error;
    } finally {
      setLoading(false);
    }
  };

  const handleSignUp = async (email: string, password: string, firstName: string, lastName: string, phone?: string): Promise<UserAuthResult> => {
    setLoading(true);
    try {
      const data = await authService.signUp(email, password, firstName, lastName, phone);
      return data;
    } catch (error: unknown) {
      console.error('Signup failed:', error); // The type of error is already 'unknown'
      throw error;
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (email: string, token: string, type: 'email' | 'phone'): Promise<UserAuthResult> => {
    setLoading(true);
    try {
      const data = await authService.verifyOtp(email, token, type);
      const currentUserData = await authService.getCurrentUser();
      setUser(currentUserData?.user || null);
      setProfile(currentUserData?.profile || null);
      return data; // Ensure this matches the return type of verifyOtp
    } catch (error: Error) {
      console.error('OTP verification failed:', error);
      throw error;
    } finally {
      setLoading(false);
    }
  };

  const value: UserContextType = React.useMemo(
    () => ({
      user,
      profile,
      loading,
      signIn: handleSignIn,
      signOut: handleSignOut,
      signUp: handleSignUp,
      verifyOtp: handleVerifyOtp,
    }),
    [user, profile, loading]
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
};
