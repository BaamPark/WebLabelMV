

from flask import Flask, request, jsonify
import os

app = Flask(__name__)

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=56250, debug=True)

