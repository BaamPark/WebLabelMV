import React from 'react';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import ProjectPage from './ProjectPage';

const AnnotationPage = () => {
  return (
    <div>
      <h1>Annotation Page</h1>
      <p>This is where video annotation will happen.</p>
    </div>
  );
};

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
