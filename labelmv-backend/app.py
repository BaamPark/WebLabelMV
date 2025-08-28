
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json

app = Flask(__name__)
CORS(app)

# In-memory storage for annotations (for simplicity)
annotations_storage = {}

@app.route('/videos', methods=['GET'])
def get_videos():
    directory = request.args.get('directory')
    if not directory:
        return jsonify({"error": "Directory parameter is required"}), 400

    if not os.path.isdir(directory):
        return jsonify({"error": "Invalid directory path"}), 400

    video_files = []
    for file in os.listdir(directory):
        if file.endswith(('.mp4', '.avi', '.mov', '.mkv')):
            video_files.append(file)

    return jsonify(video_files)

# API endpoint to save annotations for a specific video
@app.route('/api/annotations/<int:video_id>', methods=['POST'])
def save_annotations(video_id):
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid input"}), 400

    # Store annotations in memory with video ID as key
    annotations_storage[video_id] = data

    return jsonify({"success": True, "message": f"Annotations saved for video {video_id}"})

# API endpoint to get annotations for a specific video
@app.route('/api/annotations/<int:video_id>', methods=['GET'])
def get_annotations(video_id):
    # Retrieve annotations from memory
    annotations = annotations_storage.get(video_id, [])

    return jsonify(annotations)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=56250, debug=True)

