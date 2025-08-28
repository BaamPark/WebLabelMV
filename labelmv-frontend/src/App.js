

import React, { createContext, useState } from 'react';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import ProjectPage from './ProjectPage';
import AnnotationPage from './AnnotationPage';

// Create a context for sharing project data
export const ProjectContext = createContext();

function App() {
  const [projectData, setProjectData] = useState({
    numVideos: 1,
    selectedVideos: [],
  });

  return (
    <Router>
      <ProjectContext.Provider value={{ projectData, setProjectData }}>
        <Routes>
          <Route path="/" element={<ProjectPage />} />
          <Route path="/annotation" element={<AnnotationPage />} />
        </Routes>
      </ProjectContext.Provider>
    </Router>
  );
}

export default App;

