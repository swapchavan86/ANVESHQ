import React, { useState, useEffect } from 'react';
import { useUser } from '../utils/user';
import AuthLayout from '../components/AuthLayout';
import { useNavigate, useLocation } from 'react-router-dom';

const OtpVerification: React.FC = () => {
  const { verifyOtp, loading } = useUser();
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const email = (location.state as { email: string })?.email;

  useEffect(() => {
    if (!email) {
      navigate('/signup', { replace: true }); // Redirect to signup if email is missing
    }
  }, [email, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);

    if (!email) {
      // This case should ideally not be reached due to useEffect redirect
      setError('Email is missing. Cannot verify OTP.');
      return;
    }

    try {
      // Assuming OTP is for email verification. Could be extended for phone.
      await verifyOtp(email, token, 'email'); 
      setMessage('OTP verified successfully! You are now logged in.');
      navigate('/dashboard'); // Redirect to dashboard or appropriate page
    } catch (err: Error) {
      setError(err.message || 'OTP verification failed. Please try again.');
    }
  };

  return (
    <AuthLayout>
      <h2>Verify OTP</h2>
      {email ? (
        <p>An OTP has been sent to your email: <strong>{email}</strong></p>
      ) : (
        <p style={{ color: 'red' }}>{error}</p>
      )}
      
      <form onSubmit={handleSubmit}>
        {error && <p style={{ color: 'red' }}>{error}</p>}
        {message && <p style={{ color: 'green' }}>{message}</p>}
        <div>
          <label htmlFor="otp">OTP:</label>
          <input
            type="text"
            id="otp"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
            maxLength={6}
          />
        </div>
        <button type="submit" disabled={loading || !email}>
          {loading ? 'Verifying...' : 'Verify OTP'}
        </button>
      </form>
    </AuthLayout>
  );
};

export default OtpVerification;
