import React, { useState } from 'react';
import './AnnotationPage.css';

const AnnotationPage = () => {
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPoint, setStartPoint] = useState({ x: 0, y: 0 });
  const [boundingBox, setBoundingBox] = useState(null);

  const handleMouseDown = (e) => {
    if (e.button !== 0) return; // Only left mouse button
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    setIsDrawing(true);
    setStartPoint({ x, y });
    setBoundingBox({
      left: x,
      top: y,
      width: 0,
      height: 0
    });
  };

  const handleMouseMove = (e) => {
    if (!isDrawing) return;

    const rect = e.currentTarget.getBoundingClientRect();
    let x = e.clientX - rect.left;
    let y = e.clientY - rect.top;

    setBoundingBox(prev => ({
      left: Math.min(prev.left, x),
      top: Math.min(prev.top, y),
      width: Math.abs(x - prev.left),
      height: Math.abs(y - prev.top)
    }));
  };

  const handleMouseUp = () => {
    if (isDrawing) {
      setIsDrawing(false);
    }
  };

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
          <button
            className="btn btn-primary"
            onClick={() => alert("Draw bounding box tool activated")}
          >
            Draw Bounding Box
          </button>
          <button className="btn btn-secondary" disabled>Select Tool</button>
          <button className="btn btn-success" disabled>Save Annotation</button>
        </aside>

        {/* Center area for video/image display */}
        <div className="center-content">
          <div
            className="video-container"
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            {boundingBox && (
              <div
                className="bounding-box"
                style={{
                  left: boundingBox.left,
                  top: boundingBox.top,
                  width: boundingBox.width,
                  height: boundingBox.height
                }}
              />
            )}
            <div className="video-placeholder placeholder">
              <h4>Video/Image Display Area</h4>
              <p>Video or image will be displayed here</p>
            </div>
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
