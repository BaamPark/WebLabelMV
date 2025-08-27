import React, { useState } from 'react';
import './AnnotationPage.css';

const AnnotationPage = () => {
  const [isDrawing, setIsDrawing] = useState(false);
  const [boundingBoxes, setBoundingBoxes] = useState([]);

  const handleMouseDown = (e) => {
    if (e.button !== 0) return; // Only left mouse button
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    setIsDrawing(true);
    setBoundingBoxes(prev => [
      ...prev,
      {
        id: Date.now(), // Unique ID for each bounding box
        left: x,
        top: y,
        width: 0,
        height: 0
      }
    ]);
  };

  const handleMouseMove = (e) => {
    if (!isDrawing) return;

    const rect = e.currentTarget.getBoundingClientRect();
    let x = e.clientX - rect.left;
    let y = e.clientY - rect.top;

    setBoundingBoxes(prev => {
      const newBoxes = [...prev];
      const lastBox = newBoxes[newBoxes.length - 1];
      newBoxes[newBoxes.length - 1] = {
        ...lastBox,
        left: Math.min(lastBox.left, x),
        top: Math.min(lastBox.top, y),
        width: Math.abs(x - lastBox.left),
        height: Math.abs(y - lastBox.top)
      };
      return newBoxes;
    });
  };

  const handleMouseUp = () => {
    if (isDrawing) {
      setIsDrawing(false);
    }
  };

  const removeLastBoundingBox = () => {
    setBoundingBoxes(prev => prev.slice(0, -1));
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
          <button
            className="btn btn-danger"
            onClick={removeLastBoundingBox}
            disabled={boundingBoxes.length === 0}
          >
            Remove Last Bounding Box
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
            {boundingBoxes.map(box => (
              <div
                key={box.id}
                className="bounding-box"
                style={{
                  left: box.left,
                  top: box.top,
                  width: box.width,
                  height: box.height
                }}
              />
            ))}
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
            {boundingBoxes.map((box, index) => (
              <li key={box.id}>Bounding Box {index + 1}: [{box.left}, {box.top}] - [{box.width}x{box.height}]</li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
};

export default AnnotationPage;
