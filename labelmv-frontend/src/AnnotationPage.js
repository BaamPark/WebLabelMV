

import React, { useState, useRef, useContext, useEffect } from 'react';
import './AnnotationPage.css';
import { ProjectContext } from './App';

const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:56250';
const AnnotationPage = () => {
  const [isDrawingEnabled, setIsDrawingEnabled] = useState(false);
  const [boundingBoxes, setBoundingBoxes] = useState([]);
  const [isDrawing, setIsDrawing] = useState(false);
  const [draggingBoxId, setDraggingBoxId] = useState(null);
  const [resizingBoxId, setResizingBoxId] = useState(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [selectedVideoIndex, setSelectedVideoIndex] = useState(0);
  const [selectedBoxId, setSelectedBoxId] = useState(null); // Track selected box

  const { projectData } = useContext(ProjectContext);
  const { numVideos } = projectData;

  const containerRef = useRef(null);

  // Fetch annotations for the currently selected video when component mounts or video changes
  useEffect(() => {
    fetchAnnotations(selectedVideoIndex + 1); // API expects 1-based index
  }, [selectedVideoIndex]);

  // Function to save current annotations to backend before switching videos
  const saveAnnotations = async (videoId) => {
    if (boundingBoxes.length > 0) {
      try {
        await fetch(`${API_BASE}/api/annotations/${videoId}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(boundingBoxes)
        });
      } catch (error) {
        console.error('Error saving annotations:', error);
      }
    }
  };

  const fetchAnnotations = async (videoId) => {
    try {
      const response = await fetch(`${API_BASE}/api/annotations/${videoId}`);
      if (!response.ok) {
        const txt = await response.text();
        throw new Error(`GET ${response.status}: ${txt}`);
      }
      const data = await response.json();
      setBoundingBoxes(data);
    } catch (error) {
      console.error('Error fetching annotations:', error);
      setBoundingBoxes([]);
    }
  };

  const handleVideoChange = async (e) => {
    const newIndex = parseInt(e.target.value, 10) - 1; // Convert to 0-based index

    // Save current video's annotations before switching
    await saveAnnotations(selectedVideoIndex + 1);

    // Update selected video index
    setSelectedVideoIndex(newIndex);
  };

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
      setSelectedBoxId(boxId); // Highlight the box when dragging
    }
  };

  const handleResizeMouseDown = (e, boxId, corner) => {
    e.stopPropagation(); // Prevent triggering container mouse events

    if (!isDrawingEnabled && e.button === 0) { // Only left mouse button when not drawing
      setResizingBoxId({ id: boxId, corner });
      setSelectedBoxId(boxId); // Highlight the box when resizing
    }
  };

  const handleMouseMoveForResize = (e) => {
    if (resizingBoxId) {
      const rect = containerRef.current.getBoundingClientRect();
      let x = e.clientX - rect.left;
      let y = e.clientY - rect.top;

      setBoundingBoxes(prev => prev.map(box =>
        box.id === resizingBoxId.id
          ? {
              ...box,
              ...resizeBox(box, (x / rect.width) * 100, (y / rect.height) * 100, resizingBoxId.corner)
            }
          : box
      ));
    }
  };

  const handleMouseUpForResize = () => {
    if (resizingBoxId) {
      setResizingBoxId(null);
      setSelectedBoxId(null); // Unhighlight the box when done resizing
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
      setSelectedBoxId(null); // Unhighlight the box when done dragging
    }
  };

  const removeLastBoundingBox = () => {
    setBoundingBoxes(prev => prev.slice(0, -1));
  };

  // Resize box based on corner being dragged
  const resizeBox = (box, newX, newY, corner) => {
    let newBox = { ...box };

    switch(corner) {
      case 'top-left':
        newBox.width = Math.abs(newBox.left + newBox.width - newX);
        newBox.height = Math.abs(newBox.top + newBox.height - newY);
        newBox.left = newX;
        newBox.top = newY;
        break;
      case 'top-right':
        newBox.height = Math.abs(newBox.top + newBox.height - newY);
        newBox.top = newY;
        newBox.width = newX - newBox.left;
        break;
      case 'bottom-left':
        newBox.width = Math.abs(newBox.left + newBox.width - newX);
        newBox.left = newX;
        newBox.height = newY - newBox.top;
        break;
      case 'bottom-right':
        newBox.width = newX - newBox.left;
        newBox.height = newY - newBox.top;
        break;
      default:
        break;
    }

    // Ensure dimensions are positive
    if (newBox.width < 1) newBox.width = 1;
    if (newBox.height < 1) newBox.height = 1;

    return newBox;
  };
  /* The handleVideoChange function has been moved above */
  // Handle box selection from list
  const handleListItemClick = (boxId) => {
    setSelectedBoxId(boxId);
  };

  // Handle delete box from list
  const handleDeleteBox = (boxId) => {
    setBoundingBoxes(prev => prev.filter(box => box.id !== boxId));
    if (selectedBoxId === boxId) {
      setSelectedBoxId(null); // Unselect the deleted box
    }
  };

  return (
    <div
      className="annotation-page"
      onMouseMove={isDrawing ? handleMouseMove : resizingBoxId ? handleMouseMoveForResize : handleBoxMouseMove}
      onMouseUp={isDrawing ? handleMouseUp : resizingBoxId ? handleMouseUpForResize : handleBoxMouseUp}
      onMouseLeave={isDrawing ? handleMouseUp : resizingBoxId ? handleMouseUpForResize : handleBoxMouseUp}
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
          >
            {boundingBoxes.map(box => (
              <React.Fragment key={box.id}>
                <div
                  className={`bounding-box ${selectedBoxId === box.id ? 'highlighted' : ''}`}
                  style={{
                    left: `${box.left}%`,
                    top: `${box.top}%`,
                    width: `${box.width}%`,
                    height: `${box.height}%`
                  }}
                  onMouseDown={(e) => handleBoxMouseDown(e, box.id, box)}
                >
                  {/* Resize handles */}
                  <div
                    className="resize-handle top-left"
                    style={{
                      left: '0%',
                      top: '0%'
                    }}
                    onMouseDown={(e) => handleResizeMouseDown(e, box.id, 'top-left')}
                  ></div>
                  <div
                    className="resize-handle top-right"
                    style={{
                      right: '0%',
                      top: '0%'
                    }}
                    onMouseDown={(e) => handleResizeMouseDown(e, box.id, 'top-right')}
                  ></div>
                  <div
                    className="resize-handle bottom-left"
                    style={{
                      left: '0%',
                      bottom: '0%'
                    }}
                    onMouseDown={(e) => handleResizeMouseDown(e, box.id, 'bottom-left')}
                  ></div>
                  <div
                    className="resize-handle bottom-right"
                    style={{
                      right: '0%',
                      bottom: '0%'
                    }}
                    onMouseDown={(e) => handleResizeMouseDown(e, box.id, 'bottom-right')}
                  ></div>
                </div>
              </React.Fragment>
            ))}
            <div className="video-placeholder placeholder">
              <h4>Video/Image Display Area</h4>
              <p>Video or image will be displayed here</p>
            </div>
          </div>
        </div>

        {/* Right sidebar for video selection and annotation list */}
        <aside className="sidebar-right">
          {/* Video selection dropdown */}
          <div className="video-selection">
            <h4>Select Video</h4>
            <select value={selectedVideoIndex + 1} onChange={handleVideoChange}>
              {[...Array(numVideos).keys()].map((i) => (
                <option key={i} value={i + 1}>video_{i + 1}</option>
              ))}
            </select>
          </div>

          {/* Annotations list */}
          <h3>Annotations</h3>
          <ul className="annotation-list">
            {boundingBoxes.map((box, index) => (
              <li key={box.id} onClick={() => handleListItemClick(box.id)}>
                Bounding Box {index + 1}: [{box.left.toFixed(2)}%, {box.top.toFixed(2)}%] - [{box.width.toFixed(2)}% x {box.height.toFixed(2)}%]
                <i className="bi bi-trash float-right" onClick={(e) => {e.stopPropagation(); handleDeleteBox(box.id);}}></i>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
};

export default AnnotationPage;

