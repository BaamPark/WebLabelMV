import React, { useRef, useState } from 'react';
import './ChatbotPanel.css';

const readFileAsDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
  reader.onerror = () => reject(new Error('Failed to preview the selected image.'));
  reader.readAsDataURL(file);
});

const ChatbotPanel = ({ authToken, onClose }) => {
  const [prompt, setPrompt] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const imageInputRef = useRef(null);

  const resetComposer = () => {
    setPrompt('');
    setImageFile(null);
    if (imageInputRef.current) {
      imageInputRef.current.value = '';
    }
  };

  const clearImage = () => {
    setImageFile(null);
    if (imageInputRef.current) {
      imageInputRef.current.value = '';
    }
  };

  const handleImageChange = (event) => {
    const nextFile = event.target.files && event.target.files[0];
    setImageFile(nextFile || null);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();

    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt && !imageFile) {
      setError('Enter a message or attach one image.');
      return;
    }

    let uploadedImagePreviewUrl = '';
    if (imageFile) {
      try {
        uploadedImagePreviewUrl = await readFileAsDataUrl(imageFile);
      } catch (previewError) {
        setError(previewError.message);
        return;
      }
    }

    setMessages((current) => [
      ...current,
      {
        id: Date.now(),
        role: 'user',
        text: trimmedPrompt,
        imagePreviewUrl: uploadedImagePreviewUrl,
        imageName: imageFile ? imageFile.name : '',
      }
    ]);
    setIsLoading(true);
    setError('');

    const formData = new FormData();
    formData.append('text', trimmedPrompt);
    if (imageFile) {
      formData.append('image', imageFile);
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
      resetComposer();
    } catch (requestError) {
      setError(requestError.message || 'Failed to contact chatbot.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className="chatbot-panel" aria-label="AI assistant">
      <div className="chatbot-panel-header">
        <div>
          <h3>Ask AI</h3>
          <p>Ask about the current annotation task or attach one image.</p>
        </div>
        <button type="button" className="chatbot-close-button" onClick={onClose}>Close</button>
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
            {message.imagePreviewUrl && (
              <img
                alt={message.imageName || 'Uploaded preview'}
                className="chatbot-preview"
                src={message.imagePreviewUrl}
              />
            )}
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
        <label className="chatbot-label" htmlFor="annotation-chatbot-prompt">Prompt</label>
        <textarea
          id="annotation-chatbot-prompt"
          rows={4}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Ask a question about the frame or annotation."
        />

        <label className="chatbot-label" htmlFor="annotation-chatbot-image">Image</label>
        <input
          id="annotation-chatbot-image"
          ref={imageInputRef}
          type="file"
          accept="image/*"
          onChange={handleImageChange}
        />

        {imageFile && (
          <div className="chatbot-file-row">
            <span>{imageFile.name}</span>
            <button type="button" onClick={clearImage}>Remove</button>
          </div>
        )}

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
