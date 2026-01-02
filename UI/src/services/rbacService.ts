import type { UserProfile, UserRole } from '../utils/types';

export const rbacService = {
  isAdmin(profile: UserProfile | null): boolean {
    return profile?.role === 'ADMIN';
  },

  isUser(profile: UserProfile | null): boolean {
    return profile?.role === 'USER';
  },

  isDisabled(profile: UserProfile | null): boolean {
    return profile?.status === 'DISABLED';
  },

  hasPermission(profile: UserProfile | null, requiredRole: UserRole): boolean {
    if (!profile) return false;
    if (this.isDisabled(profile)) return false;

    if (requiredRole === 'ADMIN') {
      return this.isAdmin(profile);
    }
    if (requiredRole === 'USER') {
      return this.isUser(profile) || this.isAdmin(profile); // Admin can do user tasks
    }
    return false;
  },
};
