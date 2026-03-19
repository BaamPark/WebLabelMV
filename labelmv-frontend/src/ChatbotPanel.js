import React, { useState } from 'react';
import './ChatbotPanel.css';

const clampIndex = (value, maxIndex) => Math.max(0, Math.min(maxIndex, value));
const shortenLabel = (text, maxLength = 28) => {
  if (!text) return '';
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
};

const formatErrorMessage = (value, fallback) => {
  if (!value) return fallback;
  if (typeof value === 'string') return value;
  if (value instanceof Error) return value.message || fallback;
  if (typeof value === 'object') {
    if (typeof value.error === 'string') return value.error;
    if (typeof value.message === 'string') return value.message;
    try {
      return JSON.stringify(value);
    } catch (_error) {
      return fallback;
    }
  }
  return String(value);
};

const readNdjsonStream = async (response, onEvent) => {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Streaming response is not supported in this browser.');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let newlineIndex = buffer.indexOf('\n');
    while (newlineIndex >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) {
        onEvent(JSON.parse(line));
      }
      newlineIndex = buffer.indexOf('\n');
    }

    if (done) {
      const finalLine = buffer.trim();
      if (finalLine) {
        onEvent(JSON.parse(finalLine));
      }
      break;
    }
  }
};

const ChatbotPanel = ({
  authToken,
  onClose,
  onActionApplied,
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
  const activeTargetBoxId = targetBoxId;
  const sourceVideoLabel = viewLabels[activeSourceVideoIndex] || `View ${activeSourceVideoIndex + 1}`;
  const targetBoxOptions = [
    { value: 'none', label: 'None' },
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
  if (activeTargetBoxId !== 'none') {
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

  const updateMessageById = (messageId, updates) => {
    setMessages((current) => current.map((message) => (
      message.id === messageId ? { ...message, ...updates } : message
    )));
  };

  const applyActionToSessionBoxes = (baseBoxes, actionPayload, actionResult) => {
    if (!actionResult?.success || !actionPayload?.box) {
      return baseBoxes;
    }

    if (actionPayload.target_frame !== 'current') {
      return baseBoxes;
    }

    if (actionPayload.action === 'create_box') {
      return [...baseBoxes, actionPayload.box];
    }

    if (actionPayload.action === 'update_box_geometry') {
      return baseBoxes.map((box) => (
        String(box.id) === String(actionPayload.box.id) ? actionPayload.box : box
      ));
    }

    if (
      actionPayload.action === 'update_box_class' ||
      actionPayload.action === 'update_box_attributes' ||
      actionPayload.action === 'update_box_object_id'
    ) {
      return baseBoxes.map((box) => (
        String(box.id) === String(actionPayload.box.id) ? actionPayload.box : box
      ));
    }

    return baseBoxes;
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

    const userMessageId = Date.now();
    const pendingAssistantId = userMessageId + 1;
    setMessages((current) => [
      ...current,
      {
        id: userMessageId,
        role: 'user',
        text: trimmedPrompt,
        meta: `Source ${sourceVideoLabel} • frame ${activeSourceSampleIndex} • ${targetSummary} • ${targetBoxSummary}${selectedBoxId != null ? ` • UI Selected Box ${selectedBoxId}` : ''}`,
      },
      {
        id: pendingAssistantId,
        role: 'assistant',
        text: 'Waiting for response',
        meta: '',
      },
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

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(formatErrorMessage(payload.error || payload, `Request failed with status ${response.status}`));
      }
      let finalPayload = null;
      await readNdjsonStream(response, (eventPayload) => {
        if (!eventPayload || typeof eventPayload !== 'object') return;
        if (eventPayload.type === 'status') {
          updateMessageById(pendingAssistantId, {
            text: eventPayload.message || 'Waiting for response',
            meta: '',
          });
          return;
        }
        if (eventPayload.type === 'error') {
          throw new Error(formatErrorMessage(eventPayload.error || eventPayload, 'Failed to contact chatbot.'));
        }
        if (eventPayload.type === 'result') {
          finalPayload = eventPayload;
        }
      });

      if (!finalPayload) {
        throw new Error('Chatbot response ended without a final result.');
      }

      const nextSessionCurrentBoxes = applyActionToSessionBoxes(
        sessionContext ? sessionContext.currentBoxes : currentBoxes,
        finalPayload.action,
        finalPayload.actionResult,
      );

      updateMessageById(pendingAssistantId, {
        text: finalPayload.reply || '',
        meta: [
          [finalPayload.provider, finalPayload.model].filter(Boolean).join(' • '),
          finalPayload.actionResult?.message || '',
        ].filter(Boolean).join(' • '),
      });

      if (finalPayload.actionResult?.success && typeof onActionApplied === 'function') {
        onActionApplied({
          videoIndex: finalPayload.actionResult.video_index,
          sampleIndex: finalPayload.actionResult.sample_index,
          action: finalPayload.action,
          actionResult: finalPayload.actionResult,
        });
      }
      if (!sessionContext) {
        setSessionContext({
          sourceVideoIndex: currentVideoIndex,
          sourceSampleIndex: currentSampleIndex,
          targetScope,
          targetVideoIndex,
          targetSampleIndex,
          currentBoxes: nextSessionCurrentBoxes,
        });
      } else if (nextSessionCurrentBoxes !== sessionContext.currentBoxes) {
        setSessionContext((current) => ({
          ...current,
          currentBoxes: nextSessionCurrentBoxes,
        }));
      }
      resetComposer();
    } catch (requestError) {
      setMessages((current) => current.filter((message) => message.id !== pendingAssistantId));
      setError(formatErrorMessage(requestError, 'Failed to contact chatbot.'));
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
