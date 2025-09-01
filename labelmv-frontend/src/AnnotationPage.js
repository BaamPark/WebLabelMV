import React, { useState, useRef, useContext, useEffect } from 'react';
import './AnnotationPage.css';
import { ProjectContext, AuthContext } from './App';


const AnnotationPage = () => {
  const [isDrawingEnabled, setIsDrawingEnabled] = useState(false);
  const [boundingBoxes, setBoundingBoxes] = useState([]);
  const [isDrawing, setIsDrawing] = useState(false);
  const [draggingBoxId, setDraggingBoxId] = useState(null);
  const [resizingBoxId, setResizingBoxId] = useState(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [selectedVideoIndex, setSelectedVideoIndex] = useState(0);
  const [selectedBoxId, setSelectedBoxId] = useState(null); // Track selected box
  const [sampleIndex, setSampleIndex] = useState(0);
  const [sampledCount, setSampledCount] = useState(0);
  const [frameStep, setFrameStep] = useState(1);
  const [frameUrl, setFrameUrl] = useState(null);
  const [imageNatural, setImageNatural] = useState({ w: 0, h: 0 });
  const [viewportSize, setViewportSize] = useState({ w: window.innerWidth, h: window.innerHeight });
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [pendingIndex, setPendingIndex] = useState(null);

  const { projectData } = useContext(ProjectContext);
  const { authToken } = useContext(AuthContext);
  const { numVideos = 1, projectId, classes = [], attributes = {} } = projectData;

  const containerRef = useRef(null);
  const imageRef = useRef(null);
  const frameControllerRef = useRef(null);
  const annoControllerRef = useRef(null);

  // Compute displayed image metrics within the container (with object-fit: contain)
  const getDisplayMetrics = () => {
    const container = containerRef.current;
    if (!container || !imageRef.current || !imageNatural.w || !imageNatural.h) {
      return { cw: 0, ch: 0, dispW: 0, dispH: 0, offX: 0, offY: 0 };
    }
    const rect = container.getBoundingClientRect();
    const cw = rect.width;
    const ch = rect.height;
    const iw = imageNatural.w;
    const ih = imageNatural.h;
    const aspect = iw / ih;
    let dispW = cw;
    let dispH = cw / aspect;
    if (dispH > ch) {
      dispH = ch;
      dispW = ch * aspect;
    }
    const offX = (cw - dispW) / 2;
    const offY = (ch - dispH) / 2;
    return { cw, ch, dispW, dispH, offX, offY };
  };

  // Convert event client coords to normalized [0,1] within the image area
  const eventToNorm = (e) => {
    const container = containerRef.current;
    if (!container) return { x: 0, y: 0 };
    const rect = container.getBoundingClientRect();
    const { dispW, dispH, offX, offY } = getDisplayMetrics();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const x = (cx - offX) / (dispW || 1);
    const y = (cy - offY) / (dispH || 1);
    return { x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) };
  };

  // Per-frame annotations are loaded alongside frames (see loadSample)

  // Load video info and first frame on video change
  useEffect(() => {
    const load = async () => {
      setSampleIndex(0);
      await fetchVideoInfo(selectedVideoIndex);
      await loadSample(selectedVideoIndex, 0);
    };
    if (projectId) {
      load();
    }
    // Clean up image url on unmount or video change
    return () => {
      if (frameUrl) URL.revokeObjectURL(frameUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedVideoIndex, projectId]);

  // Trigger re-render on window resize so boxes recompute positions
  useEffect(() => {
    const onResize = () => setViewportSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Save current frame's annotations
  const saveAnnotations = async (videoIndex, sIndex) => {
    if (!projectId) return false;
    try {
      // ensure objectId defaults to 0 if not provided or invalid
      const boxesToSave = (boundingBoxes || []).map(b => {
        const n = parseInt(b.objectId, 10);
        return { ...b, objectId: Number.isFinite(n) ? n : 0 };
      });
      const resp = await fetch(`/api/projects/${projectId}/annotations?video_index=${videoIndex}&sample_index=${sIndex}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify(boxesToSave)
      });
      return !!resp.ok;
    } catch (error) {
      console.error('Error saving annotations:', error);
      return false;
    }
  };

  const fetchAnnotations = async (videoIndex, sIndex) => {
    if (!projectId) return;
    try {
      if (annoControllerRef.current) annoControllerRef.current.abort();
      const controller = new AbortController();
      annoControllerRef.current = controller;
      const response = await fetch(`/api/projects/${projectId}/annotations?video_index=${videoIndex}&sample_index=${sIndex}`, {
        headers: {
          'Authorization': `Bearer ${authToken}`
        },
        signal: controller.signal
      });
      if (!response.ok) {
        const txt = await response.text();
        throw new Error(`GET ${response.status}: ${txt}`);
      }
      const data = await response.json();
      setBoundingBoxes(Array.isArray(data) ? data : []);
    } catch (error) {
      if (error.name !== 'AbortError') console.error('Error fetching annotations:', error);
      setBoundingBoxes([]);
    }
  };

  const handleVideoChange = async (e) => {
    const newIndex = parseInt(e.target.value, 10) - 1; // Convert to 0-based index

    // Save current video's current-frame annotations before switching
    await saveAnnotations(selectedVideoIndex, sampleIndex);

    // Update selected video index
    setSelectedVideoIndex(newIndex);
  };

  const fetchVideoInfo = async (videoIndex) => {
    try {
      const resp = await fetch(`/api/projects/${projectId}/video_info?video_index=${videoIndex}`, {
        headers: { 'Authorization': `Bearer ${authToken}` }
      });
      if (!resp.ok) throw new Error(`video_info ${resp.status}`);
      const info = await resp.json();
      setSampledCount(info.sampled_count || 0);
      setFrameStep(info.step || 1);
    } catch (e) {
      console.error('Failed to fetch video info', e);
      setSampledCount(0);
      setFrameStep(1);
    }
  };

  const fetchFrame = async (videoIndex, sIndex) => {
    if (projectId == null) return;
    try {
      if (frameControllerRef.current) frameControllerRef.current.abort();
      const controller = new AbortController();
      frameControllerRef.current = controller;
      const resp = await fetch(`/api/projects/${projectId}/frame?video_index=${videoIndex}&sample_index=${sIndex}`, {
        headers: { 'Authorization': `Bearer ${authToken}` },
        signal: controller.signal
      });
      if (!resp.ok) throw new Error(`frame ${resp.status}`);

      // Try read headers for step/count if present
      const hStep = parseInt(resp.headers.get('X-Frame-Step'));
      const hCount = parseInt(resp.headers.get('X-Sampled-Count'));
      if (!Number.isNaN(hStep)) setFrameStep(hStep);
      if (!Number.isNaN(hCount)) setSampledCount(hCount);

      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      if (frameUrl) URL.revokeObjectURL(frameUrl);
      setFrameUrl(url);
      setSampleIndex(sIndex);
    } catch (e) {
      if (e.name !== 'AbortError') console.error('Failed to fetch frame', e);
    }
  };

  const loadSample = async (videoIndex, sIndex) => {
    await fetchFrame(videoIndex, sIndex);
    await fetchAnnotations(videoIndex, sIndex);
  };

  const gotoSample = async (s) => {
    const clamped = Math.max(0, Math.min(s, Math.max(0, sampledCount - 1)));
    if (clamped === sampleIndex) return;
    // Save current frame before moving
    await saveAnnotations(selectedVideoIndex, sampleIndex);
    await loadSample(selectedVideoIndex, clamped);
  };

  const nextSample = async () => {
    if (isScrubbing) return;
    await gotoSample(sampleIndex + 1);
  };

  const prevSample = async () => {
    if (isScrubbing) return;
    await gotoSample(sampleIndex - 1);
  };

  

  const handleSliderChange = (val) => {
    if (isScrubbing) {
      setPendingIndex(val);
    } else {
      gotoSample(val);
    }
  };

  const beginScrub = () => {
    setIsScrubbing(true);
    setPendingIndex(sampleIndex);
  };

  const endScrub = () => {
    setIsScrubbing(false);
    const target = pendingIndex != null ? pendingIndex : sampleIndex;
    setPendingIndex(null);
    if (target !== sampleIndex) gotoSample(target);
  };

  const handleDrawButtonClick = () => {
    if (isDrawingEnabled) {
      // If drawing is already enabled, disable it
      setIsDrawingEnabled(false);
    } else {
      // Otherwise enable drawing mode
      setIsDrawingEnabled(true);
    }
  };

  const handleMouseDown = (e) => {
    if (!isDrawingEnabled || e.button !== 0) return; // Only left mouse button
    const { x, y } = eventToNorm(e);
    setIsDrawing(true);
    const defaultClass = classes && classes.length > 0 ? classes[0] : '';
    // Initialize attributes with empty value so UI shows placeholders
    const defaultAttrs = Object.fromEntries(
      Object.keys(attributes || {}).map((name) => [name, ''])
    );
    setBoundingBoxes(prev => [
      ...prev,
      {
        id: Date.now(), // Unique ID for each bounding box
        left: x, // normalized [0,1]
        top: y,  // normalized [0,1]
        width: 0,
        height: 0,
        className: defaultClass,
        objectId: null,
        attributes: defaultAttrs
      }
    ]);
  };

  const handleManualSave = async () => {
    const ok = await saveAnnotations(selectedVideoIndex, sampleIndex);
    if (ok) {
      alert('Annotation saved');
    } else {
      alert('Failed to save annotation');
    }
  };

  const handleExport = async () => {
    if (!projectId) return;
    try {
      const res = await fetch(`/api/projects/${projectId}/export`, {
        headers: { 'Authorization': `Bearer ${authToken}` }
      });
      if (!res.ok) throw new Error(`export ${res.status}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `annotations_${projectId}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Export failed', e);
      alert('Export failed');
    }
  };

  const handleLoadPrelabel = async () => {
    if (!projectId) return;
    if (sampleIndex <= 0) {
      alert('No previous frame to load');
      return;
    }
    try {
      const prev = sampleIndex - 1;
      const resp = await fetch(`/api/projects/${projectId}/annotations?video_index=${selectedVideoIndex}&sample_index=${prev}`, {
        headers: { 'Authorization': `Bearer ${authToken}` }
      });
      if (!resp.ok) throw new Error(`prev annotations ${resp.status}`);
      const data = await resp.json();
      if (!Array.isArray(data) || data.length === 0) {
        alert('No annotations found in previous frame');
        return;
      }
      setBoundingBoxes(data);
      const ok = await saveAnnotations(selectedVideoIndex, sampleIndex);
      alert(ok ? 'Prelabel loaded' : 'Loaded, but saving failed');
    } catch (e) {
      console.error('Load prelabel failed', e);
      alert('Failed to load prelabel');
    }
  };

  // Import moved to Project Page

  const handleMouseMove = (e) => {
    if (!isDrawingEnabled || !isDrawing) return;
    const { x, y } = eventToNorm(e);
    setBoundingBoxes(prev => {
      const newBoxes = [...prev];
      const lastBox = newBoxes[newBoxes.length - 1];
      const x0 = lastBox.left;
      const y0 = lastBox.top;
      const left = Math.min(x0, x);
      const top = Math.min(y0, y);
      const width = Math.abs(x - x0);
      const height = Math.abs(y - y0);
      newBoxes[newBoxes.length - 1] = { ...lastBox, left, top, width, height };
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
      const { x, y } = eventToNorm(e);
      // Offset in normalized units
      const offsetX = x - box.left;
      const offsetY = y - box.top;

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
      const { x, y } = eventToNorm(e);

      setBoundingBoxes(prev => prev.map(box =>
        box.id === resizingBoxId.id
          ? {
              ...box,
              ...resizeBox(box, x, y, resizingBoxId.corner)
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
      const { x, y } = eventToNorm(e);
      // New normalized position based on offset
      const newLeft = x - dragOffset.x;
      const newTop = y - dragOffset.y;

      setBoundingBoxes(prev => prev.map(box =>
        box.id === draggingBoxId
          ? {
              ...box,
              left: Math.max(0, Math.min(1 - box.width, newLeft)),
              top: Math.max(0, Math.min(1 - box.height, newTop))
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

  // Resize box based on corner being dragged (inputs normalized [0,1])
  const resizeBox = (box, newX, newY, corner) => {
    let newBox = { ...box };

    switch(corner) {
      case 'top-left':
        newBox.width = Math.abs(newBox.left + newBox.width - newX);
        newBox.height = Math.abs(newBox.top + newBox.height - newY);
        newBox.left = Math.min(newX, newBox.left + newBox.width);
        newBox.top = Math.min(newY, newBox.top + newBox.height);
        break;
      case 'top-right':
        newBox.height = Math.abs(newBox.top + newBox.height - newY);
        newBox.top = Math.min(newY, newBox.top + newBox.height);
        newBox.width = Math.max(0, newX - newBox.left);
        break;
      case 'bottom-left':
        newBox.width = Math.abs(newBox.left + newBox.width - newX);
        newBox.left = Math.min(newX, newBox.left + newBox.width);
        newBox.height = Math.max(0, newY - newBox.top);
        break;
      case 'bottom-right':
        newBox.width = Math.max(0, newX - newBox.left);
        newBox.height = Math.max(0, newY - newBox.top);
        break;
      default:
        break;
    }

    // Ensure dimensions are positive
    const minNorm = 0.001; // minimum normalized size to keep handles usable
    if (newBox.width < minNorm) newBox.width = minNorm;
    if (newBox.height < minNorm) newBox.height = minNorm;
    // Clamp within [0,1]
    if (newBox.left < 0) newBox.left = 0;
    if (newBox.top < 0) newBox.top = 0;
    if (newBox.left + newBox.width > 1) newBox.left = 1 - newBox.width;
    if (newBox.top + newBox.height > 1) newBox.top = 1 - newBox.height;

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
        <div className="progress-controls">
          <button className="btn btn-secondary" onClick={prevSample} disabled={sampleIndex <= 0}>Previous Frame</button>
          <input
            type="range"
            min={0}
            max={Math.max(0, sampledCount - 1)}
            step={1}
            value={isScrubbing && pendingIndex != null ? pendingIndex : sampleIndex}
            onChange={(e) => handleSliderChange(parseInt(e.target.value, 10))}
            onMouseDown={beginScrub}
            onTouchStart={beginScrub}
            onMouseUp={endScrub}
            onTouchEnd={endScrub}
            disabled={sampledCount <= 0}
            className="progress-range"
          />
          <button className="btn btn-secondary" onClick={nextSample} disabled={sampleIndex >= Math.max(0, sampledCount - 1)}>Next Frame</button>
        </div>
        <div className="progress-meta">
          <span>Index: {sampleIndex} / {Math.max(0, sampledCount - 1)}</span>
          <span className="step-info">Step (raw frames): {frameStep}</span>
        </div>
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
          <button className="btn btn-success" onClick={handleManualSave}>Save Annotation</button>
          <button className="btn btn-secondary" onClick={handleLoadPrelabel}>Load prelabel</button>
          <button className="btn btn-secondary" onClick={handleExport}>Export Annotations</button>
          {/* Import moved to Project Page */}
        </aside>

        {/* Center area for video/image display */}
        <div className="center-content">
          <div
            ref={containerRef}
            className="video-container"
            onMouseDown={handleMouseDown}
          >
            {frameUrl && (
              <img
                ref={imageRef}
                src={frameUrl}
                alt="frame"
                className="video-frame"
                onLoad={(e) => setImageNatural({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
              />
            )}
            {(() => {
              const { dispW, dispH, offX, offY } = getDisplayMetrics();
              return boundingBoxes.map(box => (
              <React.Fragment key={box.id}>
                <div
                  className={`bounding-box ${selectedBoxId === box.id ? 'highlighted' : ''}`}
                  style={{
                    left: `${offX + box.left * dispW}px`,
                    top: `${offY + box.top * dispH}px`,
                    width: `${box.width * dispW}px`,
                    height: `${box.height * dispH}px`
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
            ));
            })()}
            {!frameUrl && (
              <div className="video-placeholder placeholder">
                <h4>Video/Image Display Area</h4>
                <p>Video or image will be displayed here</p>
              </div>
            )}
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
                <div className="annotation-item">
                  <span className="box-label">Box {index + 1}</span>
                  <div className="annotation-controls">
                    <select
                      value={box.className || (classes[0] || '')}
                      onChange={(e) => {
                        const v = e.target.value;
                        setBoundingBoxes(prev => prev.map(b => b.id === box.id ? { ...b, className: v } : b));
                      }}
                    >
                      {(classes.length ? classes : ['']).map((c, i) => (
                        <option key={i} value={c}>{c || 'unlabeled'}</option>
                      ))}
                    </select>
                    <input
                      type="text"
                      className="id-input"
                      placeholder="#ID"
                      value={(box.objectId == null || box.objectId === 0) ? '' : String(box.objectId)}
                      onChange={(e) => {
                        const raw = e.target.value.trim();
                        const n = parseInt(raw, 10);
                        setBoundingBoxes(prev => prev.map(b => b.id === box.id ? { ...b, objectId: Number.isFinite(n) ? n : null } : b));
                      }}
                    />
                    {Object.keys(attributes || {}).length > 0 && (
                      Object.keys(attributes).map((attrName) => (
                        <select
                          key={attrName}
                          value={(box.attributes && box.attributes[attrName]) ?? ''}
                          onChange={(e) => {
                            const v = e.target.value;
                            setBoundingBoxes(prev => prev.map(b => {
                              if (b.id !== box.id) return b;
                              const nextAttrs = { ...(b.attributes || {}) };
                              nextAttrs[attrName] = v;
                              return { ...b, attributes: nextAttrs };
                            }));
                          }}
                        >
                          <option value="" disabled>{attrName}</option>
                          {(attributes[attrName] || []).map((opt, i) => (
                            <option key={`${attrName}-${i}`} value={opt}>{opt}</option>
                          ))}
                        </select>
                      ))
                    )}
                  </div>
                  <i className="bi bi-trash" onClick={(e) => { e.stopPropagation(); handleDeleteBox(box.id); }}></i>
                </div>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
};

export default AnnotationPage;
