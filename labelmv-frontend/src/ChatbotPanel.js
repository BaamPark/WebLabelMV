import React, { useState } from 'react';
import './ChatbotPanel.css';

const clampIndex = (value, maxIndex) => Math.max(0, Math.min(maxIndex, value));
const shortenLabel = (text, maxLength = 28) => {
  if (!text) return '';
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
};

const ChatbotPanel = ({
  authToken,
  onClose,
  isOpen = false,
  projectId = '',
  currentVideoIndex = 0,
  currentSampleIndex = 0,
  sampledCount = 0,
  selectedVideos = [],
  currentBoxes = [],
  selectedBoxId = null,
}) => {
  const [prompt, setPrompt] = useState('');
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [targetScope, setTargetScope] = useState('none');
  const [targetBoxId, setTargetBoxId] = useState('none');
  const [sessionContext, setSessionContext] = useState(null);

  const videoOptions = selectedVideos.length
    ? selectedVideos
    : Array.from({ length: currentVideoIndex + 1 }, (_, index) => `Video ${index + 1}`);
  const viewLabels = videoOptions.map((videoName, index) => `View ${index + 1}: ${shortenLabel(videoName || `Video ${index + 1}`)}`);
  const maxSampleIndex = Math.max(0, sampledCount - 1);
  const activeSourceVideoIndex = sessionContext ? sessionContext.sourceVideoIndex : currentVideoIndex;
  const activeSourceSampleIndex = sessionContext ? sessionContext.sourceSampleIndex : currentSampleIndex;
  const activeCurrentBoxes = sessionContext ? sessionContext.currentBoxes : currentBoxes;
  const activeTargetScope = sessionContext ? sessionContext.targetScope : targetScope;
  const activeTargetBoxId = sessionContext ? sessionContext.targetBoxId : targetBoxId;
  const sourceVideoLabel = viewLabels[activeSourceVideoIndex] || `View ${activeSourceVideoIndex + 1}`;
  const targetBoxOptions = [
    { value: 'none', label: 'None' },
    { value: 'all', label: 'All' },
    ...activeCurrentBoxes.map((box, index) => ({
      value: String(box.id),
      label: `Box ${index + 1}${box.className ? ` • ${box.className}` : ''}${box.objectId != null && box.objectId !== 0 ? ` • ID ${box.objectId}` : ''}`,
    })),
  ];
  const targetOptions = [
    { value: 'none', label: 'None' },
    { value: 'previous_current_view', label: 'Previous Frame (Current View)' },
    { value: 'next_current_view', label: 'Next Frame (Current View)' },
    ...videoOptions
      .map((videoName, index) => ({ videoName, index }))
      .filter(({ index }) => index !== currentVideoIndex)
      .map(({ videoName, index }) => ({
        value: `view_${index}`,
        label: `${viewLabels[index] || `View ${index + 1}`} (Current Frame)`,
      })),
  ];

  let targetVideoIndex = sessionContext ? sessionContext.targetVideoIndex : activeSourceVideoIndex;
  let targetSampleIndex = sessionContext ? sessionContext.targetSampleIndex : activeSourceSampleIndex;
  let targetSummary = 'No extra target context';

  if (!sessionContext && activeTargetScope === 'previous_current_view') {
    targetSampleIndex = clampIndex(activeSourceSampleIndex - 1, maxSampleIndex);
    targetSummary = `Target ${sourceVideoLabel} frame ${targetSampleIndex}`;
  } else if (!sessionContext && activeTargetScope === 'next_current_view') {
    targetSampleIndex = clampIndex(activeSourceSampleIndex + 1, maxSampleIndex);
    targetSummary = `Target ${sourceVideoLabel} frame ${targetSampleIndex}`;
  } else if (!sessionContext && activeTargetScope.startsWith('view_')) {
    const parsedIndex = parseInt(activeTargetScope.slice(5), 10);
    if (Number.isFinite(parsedIndex)) {
      targetVideoIndex = parsedIndex;
    }
    const targetVideoLabel = viewLabels[targetVideoIndex] || `View ${targetVideoIndex + 1}`;
    targetSummary = `Target ${targetVideoLabel} frame ${targetSampleIndex}`;
  } else if (sessionContext && activeTargetScope !== 'none') {
    const targetVideoLabel = viewLabels[targetVideoIndex] || `View ${targetVideoIndex + 1}`;
    targetSummary = `Target ${targetVideoLabel} frame ${targetSampleIndex}`;
  }
  let targetBoxSummary = 'No selected box from current frame';
  if (activeTargetBoxId === 'all') {
    targetBoxSummary = 'All current-frame annotations';
  } else if (activeTargetBoxId !== 'none') {
    targetBoxSummary = `Selected box ${activeTargetBoxId} from current frame`;
  }

  const resetComposer = () => {
    setPrompt('');
  };

  const resetSession = () => {
    setPrompt('');
    setMessages([]);
    setIsLoading(false);
    setError('');
    setTargetScope('none');
    setTargetBoxId('none');
    setSessionContext(null);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();

    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      setError('Enter a message.');
      return;
    }

    const chatHistory = messages
      .filter((message) => message && message.text)
      .map((message) => ({
        role: message.role,
        text: message.text,
      }));

    setMessages((current) => [
      ...current,
      {
        id: Date.now(),
        role: 'user',
        text: trimmedPrompt,
        meta: `Source ${sourceVideoLabel} • frame ${activeSourceSampleIndex} • ${targetSummary} • ${targetBoxSummary}${selectedBoxId != null ? ` • UI Selected Box ${selectedBoxId}` : ''}`,
      }
    ]);
    setIsLoading(true);
    setError('');

    const formData = new FormData();
    formData.append('text', trimmedPrompt);
    if (projectId) {
      formData.append('project_id', projectId);
    }
    formData.append('source_video_index', String(activeSourceVideoIndex));
    formData.append('source_sample_index', String(activeSourceSampleIndex));
    formData.append('target_scope', activeTargetScope);
    if (activeTargetScope !== 'none') {
      formData.append('target_video_index', String(targetVideoIndex));
      formData.append('target_sample_index', String(targetSampleIndex));
    }
    formData.append('target_box_id', activeTargetBoxId);
    formData.append('current_boxes', JSON.stringify(activeCurrentBoxes || []));
    formData.append('chat_history', JSON.stringify(chatHistory));
    if (selectedBoxId != null) {
      formData.append('selected_box_id', String(selectedBoxId));
    }

    try {
      const response = await fetch('/api/chatbot', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
        body: formData,
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || `Request failed with status ${response.status}`);
      }

      setMessages((current) => [
        ...current,
        {
          id: Date.now() + 1,
          role: 'assistant',
          text: payload.reply || '',
          meta: [payload.provider, payload.model].filter(Boolean).join(' • '),
        },
      ]);
      if (!sessionContext) {
        setSessionContext({
          sourceVideoIndex: currentVideoIndex,
          sourceSampleIndex: currentSampleIndex,
          targetScope,
          targetVideoIndex,
          targetSampleIndex,
          targetBoxId,
          currentBoxes,
        });
      }
      resetComposer();
    } catch (requestError) {
      setError(requestError.message || 'Failed to contact chatbot.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className={`chatbot-panel ${isOpen ? '' : 'chatbot-panel-hidden'}`} aria-label="AI assistant">
      <div className="chatbot-panel-header">
        <div>
          <h3>Ask AI</h3>
          <p>Ask about the current annotation task and choose one target frame.</p>
        </div>
        <div className="chatbot-panel-header-actions">
          <button type="button" className="chatbot-renew-button" onClick={resetSession}>Renew</button>
          <button type="button" className="chatbot-close-button" onClick={onClose}>Close</button>
        </div>
      </div>

      <div className="chatbot-panel-messages">
        {messages.length === 0 && (
          <div className="chatbot-empty">
            Start with a question like "What objects are visible in this frame?"
          </div>
        )}

        {messages.map((message) => (
          <div key={message.id} className={`chatbot-message chatbot-message-${message.role}`}>
            <div className="chatbot-message-role">{message.role === 'user' ? 'You' : 'Assistant'}</div>
            {message.text && <div className="chatbot-message-text">{message.text}</div>}
            {message.meta && <div className="chatbot-message-meta">{message.meta}</div>}
          </div>
        ))}

        {isLoading && (
          <div className="chatbot-message chatbot-message-assistant">
            <div className="chatbot-message-role">Assistant</div>
            <div className="chatbot-message-text">Thinking...</div>
          </div>
        )}
      </div>

      <form className="chatbot-panel-composer" onSubmit={handleSubmit}>
        <label className="chatbot-label" htmlFor="annotation-chatbot-target-scope">Target Frame</label>
        <select
          id="annotation-chatbot-target-scope"
          value={activeTargetScope}
          onChange={(event) => setTargetScope(event.target.value)}
          disabled={!!sessionContext}
        >
          {targetOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        <label className="chatbot-label" htmlFor="annotation-chatbot-target-box">Selected Box From Current Frame</label>
        <select
          id="annotation-chatbot-target-box"
          value={activeTargetBoxId}
          onChange={(event) => setTargetBoxId(event.target.value)}
          disabled={!!sessionContext}
        >
          {targetBoxOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        <label className="chatbot-label" htmlFor="annotation-chatbot-prompt">Prompt</label>
        <textarea
          id="annotation-chatbot-prompt"
          rows={4}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Ask a question about the frame or annotation."
        />

        {error && <div className="chatbot-error">{error}</div>}

        <div className="chatbot-actions">
          <button type="submit" disabled={isLoading}>
            {isLoading ? 'Sending...' : 'Send'}
          </button>
        </div>
      </form>
    </section>
  );
};

export default ChatbotPanel;
