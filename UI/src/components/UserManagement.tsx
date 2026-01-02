import React, { useEffect, useState } from 'react';
import { adminService } from '../services/adminService';
import type { UserProfile, UserStatus } from '../utils/types';
import { useUser } from '../utils/user';
import { rbacService } from '../services/rbacService';
import { useNavigate } from 'react-router-dom';

const UserManagement: React.FC = () => {
  const { profile, loading: userLoading } = useUser();
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!userLoading && (!profile || !rbacService.isAdmin(profile))) {
      navigate('/'); // Redirect non-admin users
      return;
    }

    const fetchUsers = async () => {
      try {
        setLoading(true);
        const fetchedUsers = await adminService.getAllUsers();
        setUsers(fetchedUsers);
      } catch (err: Error) {
        setError(err.message || 'Failed to fetch users.');
      } finally {
        setLoading(false);
      }
    };

    if (profile && rbacService.isAdmin(profile)) {
      fetchUsers();
    }
  }, [profile, userLoading, navigate]);

  const handleStatusChange = async (userId: string, currentStatus: UserStatus) => {
    const newStatus = currentStatus === 'ACTIVE' ? 'DISABLED' : 'ACTIVE';
    try {
      setLoading(true);
      await adminService.updateUserStatus(userId, newStatus);
      // Update local state to reflect the change
      setUsers(prevUsers =>
        prevUsers.map(user =>
          user.id === userId ? { ...user, status: newStatus } : user
        )
      );
    } catch (err: Error) {
      setError(err.message || 'Failed to update user status.');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteUser = async (userId: string) => {
    if (!window.confirm('Are you sure you want to delete this user?')) {
      return;
    }
    try {
      setLoading(true);
      await adminService.deleteUser(userId);
      // Remove user from local state
      setUsers(prevUsers => prevUsers.filter(user => user.id !== userId));
    } catch (err: Error) {
      setError(err.message || 'Failed to delete user.');
    } finally {
      setLoading(false);
    }
  };

  if (userLoading || loading) {
    return <p>Loading user management...</p>;
  }

  if (error) {
    return <p style={{ color: 'red' }}>Error: {error}</p>;
  }

  return (
    <div className="p-4">
      <h1 className="text-3xl font-bold mb-4">User Management</h1>
      <table className="min-w-full bg-white border border-gray-200">
        <thead>
          <tr>
            <th className="py-2 px-4 border-b">Email</th>
            <th className="py-2 px-4 border-b">First Name</th>
            <th className="py-2 px-4 border-b">Last Name</th>
            <th className="py-2 px-4 border-b">Role</th>
            <th className="py-2 px-4 border-b">Status</th>
            <th className="py-2 px-4 border-b">Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id}>
              <td className="py-2 px-4 border-b">{user.email}</td>
              <td className="py-2 px-4 border-b">{user.first_name}</td>
              <td className="py-2 px-4 border-b">{user.last_name}</td>
              <td className="py-2 px-4 border-b">{user.role}</td>
              <td className="py-2 px-4 border-b">{user.status}</td>
              <td className="py-2 px-4 border-b">
                <button
                  onClick={() => handleStatusChange(user.id, user.status)}
                  className={`mr-2 ${user.status === 'ACTIVE' ? 'bg-yellow-500' : 'bg-green-500'} text-white py-1 px-2 rounded`}
                >
                  {user.status === 'ACTIVE' ? 'Disable' : 'Enable'}
                </button>
                <button
                  onClick={() => handleDeleteUser(user.id)}
                  className="bg-red-500 text-white py-1 px-2 rounded"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default UserManagement;
