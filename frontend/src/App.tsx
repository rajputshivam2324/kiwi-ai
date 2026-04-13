import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { SignedIn, SignedOut, RedirectToSignIn } from '@clerk/clerk-react';
import { AuthLandingPage } from './pages/AuthLandingPage';
import { LandingPage } from './pages/LandingPage';
import { ChatPage } from './pages/ChatPage';
import { BuilderPage } from './pages/BuilderPage';

function App() {
  return (
    <Router>
      <Routes>
        {/* Main Marketing Landing Page */}
        <Route path="/" element={<LandingPage />} />

        {/* Authentication page */}
        <Route path="/auth" element={
          <>
            <SignedIn>
              <Navigate to="/chat" replace />
            </SignedIn>
            <SignedOut>
              <AuthLandingPage />
            </SignedOut>
          </>
        } />

        {/* Chat interface - protected */}
        <Route path="/chat" element={
          <>
            <SignedIn>
              <ChatPage />
            </SignedIn>
            <SignedOut>
              <RedirectToSignIn />
            </SignedOut>
          </>
        } />

        {/* Builder/IDE - protected */}
        <Route
          path="/builder"
          element={
            <>
              <SignedIn>
                <BuilderPage />
              </SignedIn>
              <SignedOut>
                <RedirectToSignIn />
              </SignedOut>
            </>
          }
        />
      </Routes>
    </Router>
  );
}

export default App;
