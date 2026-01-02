import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { UserProvider } from './components/UserProvider';
import { Layout } from './components/Layout';
import { HomePage } from './components/HomePage';
import { SignIn } from './components/SignIn';
import { SignUp } from './components/SignUp';
import { StockDetails } from './components/StockDetails';
import { AboutUs } from './components/AboutUs';
import { ContactUs } from './components/ContactUs';

export const App: React.FC = () => {
  return (
    <Router>
      <UserProvider>
        <Routes>
          <Route element={<Layout><HomePage /></Layout>} path="/" />
          <Route element={<Layout><SignIn /></Layout>} path="/signin" />
          <Route element={<Layout><SignUp /></Layout>} path="/signup" />
          <Route element={<Layout><StockDetails /></Layout>} path="/stocks/:symbol" />
          <Route element={<Layout><AboutUs /></Layout>} path="/about" />
          <Route element={<Layout><ContactUs /></Layout>} path="/contact" />
        </Routes>
      </UserProvider>
    </Router>
  );
};