import React, { useState, useRef } from 'react';
import './AnnotationPage.css';

const AnnotationPage = () => {
  const [isDrawingEnabled, setIsDrawingEnabled] = useState(false);
  const [boundingBoxes, setBoundingBoxes] = useState([]);
  const [isDrawing, setIsDrawing] = useState(false);
  const [draggingBoxId, setDraggingBoxId] = useState(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });

  const containerRef = useRef(null);

  const handleDrawButtonClick = () => {
    if (isDrawingEnabled) {
      // If drawing is already enabled, disable it
      setIsDrawingEnabled(false);
    } else {
      // Otherwise enable drawing mode
      setIsDrawingEnabled(true);
      alert("Draw bounding box tool activated - click and drag to draw");
    }
  };

  const handleMouseDown = (e) => {
    if (!isDrawingEnabled || e.button !== 0) return; // Only left mouse button when drawing is enabled

    const rect = containerRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    setIsDrawing(true);
    setBoundingBoxes(prev => [
      ...prev,
      {
        id: Date.now(), // Unique ID for each bounding box
        left: (x / rect.width) * 100, // Store as percentage of container width
        top: (y / rect.height) * 100, // Store as percentage of container height
        width: 0,
        height: 0
      }
    ]);
  };

  const handleMouseMove = (e) => {
    if (!isDrawingEnabled || !isDrawing) return;

    const rect = containerRef.current.getBoundingClientRect();
    let x = e.clientX - rect.left;
    let y = e.clientY - rect.top;

    setBoundingBoxes(prev => {
      const newBoxes = [...prev];
      const lastBox = newBoxes[newBoxes.length - 1];
      newBoxes[newBoxes.length - 1] = {
        ...lastBox,
        left: Math.min(lastBox.left, (x / rect.width) * 100),
        top: Math.min(lastBox.top, (y / rect.height) * 100),
        width: Math.abs((x / rect.width) * 100 - lastBox.left),
        height: Math.abs((y / rect.height) * 100 - lastBox.top)
      };
      return newBoxes;
    });
  };

  const handleMouseUp = () => {
    if (isDrawing) {
      setIsDrawing(false);
      // Automatically disable drawing mode after a box is drawn
      setIsDrawingEnabled(false);
    }
  };

  const handleBoxMouseDown = (e, boxId, box) => {
    e.stopPropagation(); // Prevent triggering container mouse events

    if (!isDrawingEnabled && e.button === 0) { // Only left mouse button when not drawing
      const rect = containerRef.current.getBoundingClientRect();

      // Calculate offset from click position to top-left corner of the bounding box
      const offsetX = ((e.clientX - rect.left) / rect.width * 100) - box.left;
      const offsetY = ((e.clientY - rect.top) / rect.height * 100) - box.top;

      setDraggingBoxId(boxId);
      setDragOffset({ x: offsetX, y: offsetY });
    }
  };

  const handleBoxMouseMove = (e) => {
    if (draggingBoxId !== null) {
      const rect = containerRef.current.getBoundingClientRect();
      let x = e.clientX - rect.left;
      let y = e.clientY - rect.top;

      // Calculate new position based on offset
      const newLeft = ((x / rect.width) * 100) - dragOffset.x;
      const newTop = ((y / rect.height) * 100) - dragOffset.y;

      setBoundingBoxes(prev => prev.map(box =>
        box.id === draggingBoxId
          ? {
              ...box,
              left: Math.max(0, Math.min(100, newLeft)), // Clamp to container bounds
              top: Math.max(0, Math.min(100, newTop))
            }
          : box
      ));
    }
  };

  const handleBoxMouseUp = () => {
    if (draggingBoxId !== null) {
      setDraggingBoxId(null);
    }
  };

  const removeLastBoundingBox = () => {
    setBoundingBoxes(prev => prev.slice(0, -1));
  };

  return (
    <div
      className="annotation-page"
      onMouseMove={handleBoxMouseMove}
      onMouseUp={handleBoxMouseUp}
      onMouseLeave={handleBoxMouseUp}
    >
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
            className={`btn ${isDrawingEnabled ? 'btn-warning' : 'btn-primary'}`}
            onClick={handleDrawButtonClick}
          >
            {isDrawingEnabled ? "Drawing Enabled" : "Draw Bounding Box"}
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
            ref={containerRef}
            className="video-container"
            onMouseDown={handleMouseDown}
            onMouseMove={isDrawing ? handleMouseMove : undefined}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            {boundingBoxes.map(box => (
              <div
                key={box.id}
                className="bounding-box"
                style={{
                  left: `${box.left}%`,
                  top: `${box.top}%`,
                  width: `${box.width}%`,
                  height: `${box.height}%`
                }}
                onMouseDown={(e) => handleBoxMouseDown(e, box.id, box)}
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
              <li key={box.id}>Bounding Box {index + 1}: [{box.left}%, {box.top}%] - [{box.width}% x {box.height}%</li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
};

export default AnnotationPage;
