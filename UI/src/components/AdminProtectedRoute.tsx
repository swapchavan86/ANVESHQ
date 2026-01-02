import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useUser } from '../utils/user';
import { rbacService } from '../services/rbacService';

interface AdminProtectedRouteProps {
  children: React.ReactNode;
}

const AdminProtectedRoute: React.FC<AdminProtectedRouteProps> = ({ children }) => {
  const { user, profile, loading } = useUser();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && (!user || !profile || !rbacService.isAdmin(profile))) {
      // Redirect to home or a forbidden page if not an admin
      navigate('/'); 
    }
  }, [user, profile, loading, navigate]);

  if (loading) {
    return <p>Loading...</p>;
  }

  // Only render children if user is logged in, has a profile, and is an admin
  if (user && profile && rbacService.isAdmin(profile)) {
    return <>{children}</>;
  }

  return null; // Don't render anything if not authorized, useEffect handles redirection
};

export default AdminProtectedRoute;
