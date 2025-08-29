



import React, { createContext, useState } from 'react';
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import ProjectPage from './ProjectPage';
import AnnotationPage from './AnnotationPage';
import SignUp from './SignUp';
import SignIn from './SignIn';

// Create a context for sharing project data
export const ProjectContext = createContext();

// Create a context for authentication state
export const AuthContext = createContext();

function App() {
  const [projectData, setProjectData] = useState({
    numVideos: 1,
    selectedVideos: [],
  });

  const [authToken, setAuthToken] = useState(null);

  // Handle sign up success
  const handleSignUp = (token) => {
    setAuthToken(token);
  };

  // Handle sign in success
  const handleSignIn = (token) => {
    setAuthToken(token);
  };

  return (
    <Router>
      <AuthContext.Provider value={{ authToken, setAuthToken }}>
        <ProjectContext.Provider value={{ projectData, setProjectData }}>
          <Routes>
            <Route path="/" element={<Navigate to="/signin" replace />} />
            <Route path="/project" element={
              authToken ? <ProjectPage /> : <Navigate to="/signin" />
            } />
            <Route path="/annotation" element={
              authToken ? <AnnotationPage /> : <Navigate to="/signin" />
            } />
            <Route path="/signup" element={<SignUp onSignUp={handleSignUp} />} />
            <Route path="/signin" element={<SignIn onSignIn={handleSignIn} replacePath="/project" />} />
          </Routes>
        </ProjectContext.Provider>
      </AuthContext.Provider>
    </Router>
  );
}

export default App;

