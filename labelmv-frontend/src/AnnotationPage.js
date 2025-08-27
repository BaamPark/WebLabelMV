

import React from 'react';
import './AnnotationPage.css';

const AnnotationPage = () => {
  return (
    <div className="annotation-page">
      {/* Header for video progress bar */}
      <header className="header">
        <h2>Video Progress Bar</h2>
        <div className="progress-placeholder">Progress bar goes here</div>
      </header>

      {/* Main content area with three columns */}
      <div className="content">
        {/* Left sidebar for buttons */}
        <aside className="sidebar-left">
          <h3>Tools</h3>
          <button className="btn btn-primary" disabled>Draw Bounding Box</button>
          <button className="btn btn-secondary" disabled>Select Tool</button>
          <button className="btn btn-success" disabled>Save Annotation</button>
        </aside>

        {/* Center area for video/image display */}
        <div className="center-content">
          <div className="video-placeholder placeholder">
            <h4>Video/Image Display Area</h4>
            <p>Video or image will be displayed here</p>
          </div>
        </div>

        {/* Right sidebar for annotation list */}
        <aside className="sidebar-right">
          <h3>Annotations</h3>
          <ul className="annotation-list placeholder">
            <li>Annotation 1</li>
            <li>Annotation 2</li>
            <li>Annotation 3</li>
          </ul>
        </aside>
      </div>
    </div>
  );
};

export default AnnotationPage;

