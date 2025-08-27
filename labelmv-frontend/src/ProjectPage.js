import "./ProjectPage.css";
import React, { useState } from 'react';

const ProjectPage = () => {
  const [numVideos, setNumVideos] = useState(1);
  const [videoFiles, setVideoFiles] = useState(Array(numVideos).fill(null));
  const [frameRate, setFrameRate] = useState(1);

  const handleNumVideosChange = (e) => {
    const count = parseInt(e.target.value);
    setNumVideos(count);
    // Initialize video files array with null values
    setVideoFiles(Array(count).fill(null));
  };

  const handleVideoChange = (index, e) => {
    const newFiles = [...videoFiles];
    newFiles[index] = e.target.files[0];
    setVideoFiles(newFiles);
  };

  const handleFrameRateChange = (e) => {
    setFrameRate(parseInt(e.target.value));
  };

  return (
    <div className="project-page">
      <h1>LabelMV Project Page</h1>

      <section>
        <h2>Number of Videos</h2>
        <select value={numVideos} onChange={handleNumVideosChange}>
          {[...Array(10).keys()].map((i) => (
            <option key={i + 1} value={i + 1}>{i + 1}</option>
          ))}
        </select>
      </section>

      <section>
        <h2>Upload Videos</h2>
        {Array.from({ length: numVideos }, (_, i) => (
          <div key={i}>
            <label htmlFor={`video-${i}`}>Choose video {i + 1}</label>
            <input
              id={`video-${i}`}
              type="file"
              accept="video/*"
              onChange={(e) => handleVideoChange(i, e)}
            />
          </div>
        ))}
      </section>

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

    </div>
  );
};

export default ProjectPage;
