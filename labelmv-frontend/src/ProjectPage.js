


import "./ProjectPage.css";
import React, { useState, useContext } from 'react';
import { useNavigate } from 'react-router-dom';
import { ProjectContext } from './App';
const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:56250';

const ProjectPage = () => {
  const [videoDirectory, setVideoDirectory] = useState('');
  const [availableVideos, setAvailableVideos] = useState([]);
  const [numVideos, setNumVideos] = useState(1);
  const [selectedVideos, setSelectedVideos] = useState(Array(numVideos).fill(null));
  const [frameRate, setFrameRate] = useState(1);

  const { setProjectData } = useContext(ProjectContext);

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
  const startAnnotation = () => {
    setProjectData({ numVideos, selectedVideos });
    navigate('/annotation');
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

