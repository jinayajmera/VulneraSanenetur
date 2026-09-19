import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LandingPage } from './pages/LandingPage';
import { AuthPage } from './pages/AuthPage';
import { ConsolePage } from './pages/ConsolePage';
import { ApiService } from './services/api';
import { UserAuth } from './types/robosurge';

export const App: React.FC = () => {
  const [user, setUser] = useState<UserAuth | null>(null);
  const [authInitialized, setAuthInitialized] = useState(false);

  useEffect(() => {
    // Check if token exists, try auto-login / verify session
    ApiService.autoLogin()
      .then((u) => {
        if (u) setUser(u);
      })
      .finally(() => {
        setAuthInitialized(true);
      });
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        {/* Landing Page */}
        <Route path="/" element={<LandingPage user={user} />} />

        {/* Dedicated Auth Page */}
        <Route 
          path="/auth" 
          element={
            <AuthPage 
              currentUser={user} 
              onLoginSuccess={(u) => setUser(u)}
              onLogout={() => {
                ApiService.clearToken();
                setUser(null);
              }}
            />
          } 
        />

        {/* Surgical Console (Dashboard) */}
        <Route 
          path="/console" 
          element={
            <ConsolePage 
              user={user} 
              setUser={setUser} 
            />
          } 
        />

        {/* Catch-all Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
