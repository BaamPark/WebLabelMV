import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import './AuthPage.css';

const SignUp = ({ onSignUp }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();

    try {
      const response = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ username, password })
      });

      const data = await response.json();

      if (!response.ok) {
        // show error message from backend
        if (data.error === "User already exists") {
          alert("User already exists! Please sign in.");
        } else {
          alert("Sign up failed.");
        }
        return;
      }

      // Success
      alert("Account created successfully!");
      onSignUp(data.token);

      // Optional: redirect to sign in page after signup
      navigate('/signin');

    } catch (error) {
      console.error('Error signing up:', error);
      alert("Error occurred while signing up.");
    }
  };

  return (
    <div className="auth-page">
      <h2>Sign Up</h2>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="username">Username:</label>
          <input
            type="text"
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>
        <div className="form-group">
          <label htmlFor="password">Password:</label>
          <input
            type="password"
            id="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        <button type="submit" className="btn btn-primary">Sign Up</button>
      </form>

      <p>Already have an account? <Link to="/signin">Sign In</Link></p>
    </div>
  );
};

export default SignUp;
