import { supabase } from './supabaseClient';
import type { UserProfile, UserStatus } from '../utils/types';

export const adminService = {
  async getAllUsers(): Promise<UserProfile[]> {
    try {
      const { data, error } = await supabase
        .from('users')
        .select('*');

      if (error) throw error;
      return data as UserProfile[];
    } catch (error) {
      console.error('Error fetching all users:', error);
      throw error;
    }
  },

  async updateUserStatus(userId: string, status: UserStatus): Promise<UserProfile> {
    try {
      const { data, error } = await supabase
        .from('users')
        .update({ status: status })
        .eq('id', userId)
        .select() // Use select() to return the updated row
        .single();

      if (error) throw error;
      return data as UserProfile;
    } catch (error) {
      console.error(`Error updating user ${userId} status to ${status}:`, error);
      throw error;
    }
  },

  async deleteUser(userId: string): Promise<void> {
    try {
      // First delete user from public.users table (profile)
      const { error: profileError } = await supabase
        .from('users')
        .delete()
        .eq('id', userId);

      if (profileError) throw profileError;

      // Then delete from auth.users (Supabase Auth) - Requires service_role_key
      // Note: This requires a server-side context or a very carefully managed client-side service_role_key
      // For client-side, typically only authenticated users can delete themselves.
      // Admin deleting other users usually happens via a backend function (Supabase Edge Function or custom API)
      // For now, let's assume we can only delete the profile data on client,
      // or that the RLS policies in Supabase handle auth.users deletion for admin.
      // If direct auth.users deletion is needed from client, it will need a RLS policy on auth.users
      // or an admin role on the client which is generally not recommended.
      // Let's assume for now, deleting the profile is sufficient from the client, and a backend trigger
      // handles auth.users deletion if needed.
      
      console.log(`User profile ${userId} deleted successfully.`);
      // If you were to delete from auth.users from client (NOT RECOMMENDED):
      // const { error: authError } = await supabase.auth.admin.deleteUser(userId);
      // if (authError) throw authError;

    } catch (error) {
      console.error(`Error deleting user ${userId}:`, error);
      throw error;
    }
  },
};
