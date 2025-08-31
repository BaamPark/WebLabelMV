


import "./ProjectPage.css";
import React, { useState, useContext } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ProjectContext, AuthContext } from './App';
const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:56250';

const ProjectPage = () => {
  const [videoDirectory, setVideoDirectory] = useState('');
  const [availableVideos, setAvailableVideos] = useState([]);
  const [numVideos, setNumVideos] = useState(1);
  const [selectedVideos, setSelectedVideos] = useState(Array(numVideos).fill(null));
  const [frameRate, setFrameRate] = useState(1);
  const [classesText, setClassesText] = useState("");
  const [attributesText, setAttributesText] = useState("");

  const { setProjectData } = useContext(ProjectContext);
  const { authToken } = useContext(AuthContext);

  const navigate = useNavigate();

  // Step 1: Set video directory and fetch videos
  const handleSetPathClick = () => {
    fetch(`${API_BASE}/videos?directory=${encodeURIComponent(videoDirectory)}`)
      .then(response => response.json())
      .then(data => {
        if (data.error) {
          console.error('Error fetching videos:', data.error);
        } else {
          setAvailableVideos(data);
        }
      })
      .catch(error => console.error('Error fetching videos:', error));
  };

  // Step 2: Set number of videos
  const handleNumVideosChange = (e) => {
    const count = parseInt(e.target.value);
    setNumVideos(count);
    // Initialize selected videos array with null values
    setSelectedVideos(Array(count).fill(null));
  };

  // Step 3: Select a video
  const handleVideoChange = (index, e) => {
    const newSelection = [...selectedVideos];
    newSelection[index] = e.target.value;
    setSelectedVideos(newSelection);
  };

  // Step 4: Set frame rate
  const handleFrameRateChange = (e) => {
    setFrameRate(parseInt(e.target.value));
  };

  // Navigate to annotation page and save project data
  const startAnnotation = async () => {
    try {
      const classes = classesText
        .split(/\n|,/)
        .map(s => s.trim())
        .filter(Boolean);

      // Parse attributes text. Supported formats:
      // name: {opt1, opt2} OR name: opt1, opt2
      const attributes = {};
      attributesText.split(/\n/).forEach((line) => {
        const raw = line.trim();
        if (!raw) return;
        const colonIdx = raw.indexOf(":");
        if (colonIdx === -1) return;
        const name = raw.slice(0, colonIdx).trim();
        if (!name) return;
        let rest = raw.slice(colonIdx + 1).trim();
        if (rest.startsWith("{") && rest.endsWith("}")) {
          rest = rest.slice(1, -1).trim();
        }
        const options = rest
          .split(/,/)
          .map(s => s.trim())
          .filter(Boolean);
        if (options.length) {
          attributes[name] = options;
        }
      });

      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({
          videoDirectory,
          selectedVideos,
          fps: frameRate,
          classes,
          attributes
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Failed to create project: ${res.status} ${txt}`);
      }
      const data = await res.json();
      setProjectData({
        projectId: data.projectId,
        videoDirectory: data.videoDirectory,
        selectedVideos: data.selectedVideos,
        fps: data.fps,
        classes: data.classes || classes || [],
        attributes: data.attributes || attributes || {},
        numVideos: selectedVideos.length
      });
      navigate('/annotation');
    } catch (e) {
      console.error(e);
      alert('Failed to start annotation. Check server logs.');
    }
  };

  return (
    <div className="project-page">
      <h1>LabelMV Project Page</h1>

      {/* Step 1: Video Directory */}
      <section>
        <h2>Video Directory</h2>
        <input
          type="text"
          value={videoDirectory}
          onChange={(e) => setVideoDirectory(e.target.value)}
          placeholder="Enter path to video directory"
        />
        <button onClick={handleSetPathClick}>Set Path</button>
      </section>

      {/* Step 2: Number of Videos (shown after setting path) */}
      {availableVideos.length > 0 && (
        <section>
          <h2>Number of Videos</h2>
          <select value={numVideos} onChange={handleNumVideosChange}>
            {[...Array(10).keys()].map((i) => (
              <option key={i + 1} value={i + 1}>{i + 1}</option>
            ))}
          </select>
        </section>
      )}

      {/* Step 3: Select Videos (shown after setting number of videos) */}
      {numVideos > 0 && availableVideos.length > 0 && (
        <section>
          <h2>Select Videos</h2>
          {Array.from({ length: numVideos }, (_, i) => (
            <div key={i}>
              <label htmlFor={`video-${i}`}>Video {i + 1}</label>
              <select
                id={`video-${i}`}
                value={selectedVideos[i] || ''}
                onChange={(e) => handleVideoChange(i, e)}
              >
                <option value="">Select a video</option>
                {availableVideos.map((video, index) => (
                  <option key={index} value={video}>{video}</option>
                ))}
              </select>
            </div>
          ))}
        </section>
      )}

      {/* Step 4: Set Frame Rate (shown after selecting videos) */}
      {selectedVideos.length > 0 && selectedVideos.every(video => video !== null && video !== '') && (
        <section>
          <h2>Set Frame Rate</h2>
          <input
            type="number"
            value={frameRate}
            onChange={handleFrameRateChange}
            min="1"
          />
          <p>Frames per second (FPS): {frameRate}</p>
        </section>
      )}

      {/* Step 5: Define Classes (optional) */}
      {selectedVideos.length > 0 && selectedVideos.every(video => video !== null && video !== '') && (
        <section>
          <h2>Classes</h2>
          <p>Enter one class per line or comma-separated. First class is default.</p>
          <textarea
            rows={4}
            value={classesText}
            onChange={(e) => setClassesText(e.target.value)}
            placeholder="e.g.\nmask\ngown"
            style={{ width: '100%' }}
          />
        </section>
      )}

      {/* Step 6: Define Attributes (optional) */}
      {selectedVideos.length > 0 && selectedVideos.every(video => video !== null && video !== '') && (
        <section>
          <h2>Attributes</h2>
          <p>One per line: name: {`{`}option1, option2{`}`}. Applies to each box.</p>
          <textarea
            rows={4}
            value={attributesText}
            onChange={(e) => setAttributesText(e.target.value)}
            placeholder={"mask: {mask absent, mask complete}\ngown: {gown absent, gown complete}"}
            style={{ width: '100%' }}
          />
        </section>
      )}

      {/* Start Annotation Button (shown after receiving video list) */}
      {availableVideos.length > 0 && (
        <section>
          <button onClick={startAnnotation}>Start Annotation</button>
        </section>
      )}
    </div>
  );
};

export default ProjectPage;
