import React from 'react';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import ProjectPage from './ProjectPage';
import AnnotationPage from './AnnotationPage';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<ProjectPage />} />
        <Route path="/annotation" element={<AnnotationPage />} />
      </Routes>
    </Router>
  );
}

export default App;
