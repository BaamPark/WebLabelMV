


from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import jwt
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_pymongo import PyMongo
from functools import wraps
from bson import ObjectId

app = Flask(__name__)
CORS(app)

# Configure MongoDB connection (replace with your actual MongoDB URI)
app.config['MONGO_URI'] = 'mongodb://localhost:27017/labelmv'
mongo = PyMongo(app)

# Secret key for JWT
app.config['SECRET_KEY'] = 'your_secret_key_here'

# In-memory storage for annotations (for simplicity, will be replaced with database)
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

# User registration endpoint
@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.get_json()

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    # Check if user already exists
    existing_user = mongo.db.users.find_one({"username": username})
    if existing_user:
        return jsonify({"error": "User already exists"}), 400

    # Hash the password and store user in database
    hashed_password = generate_password_hash(password, method='sha256')
    mongo.db.users.insert_one({
        "username": username,
        "password": hashed_password
    })

    return jsonify({"message": "User registered successfully"}), 201

# User login endpoint
@app.route('/api/auth/signin', methods=['POST'])
def signin():
    data = request.get_json()

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    # Find user in database
    user = mongo.db.users.find_one({"username": username})

    if not user or not check_password_hash(user['password'], password):
        return jsonify({"error": "Invalid credentials"}), 401

    # Create JWT token
    token = jwt.encode({
        'user_id': str(user['_id']),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, app.config['SECRET_KEY'])

    return jsonify({"token": token})

# Middleware to verify JWT token
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]

        if not token:
            return jsonify({"error": "Token is missing"}), 403

        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = mongo.db.users.find_one({"_id": ObjectId(data['user_id'])})
        except Exception as e:
            return jsonify({"error": "Token is invalid", "message": str(e)}), 403

        return f(current_user, *args, **kwargs)

    return decorated

# API endpoint to save annotations for a specific video
@app.route('/api/annotations/<int:video_id>', methods=['POST'])
@token_required
def save_annotations(current_user, video_id):
    data = request.get_json()

    if data is None:
        return jsonify({"error": "Invalid input"}), 400

    # Store annotations in memory with user ID and video ID as key
    user_id = str(current_user['_id'])
    annotations_storage[(user_id, video_id)] = data

    return jsonify({"success": True, "message": f"Annotations saved for video {video_id}"})

# API endpoint to get annotations for a specific video
@app.route('/api/annotations/<int:video_id>', methods=['GET'])
@token_required
def get_annotations(current_user, video_id):
    # Retrieve annotations from memory
    user_id = str(current_user['_id'])
    annotations = annotations_storage.get((user_id, video_id), [])

    return jsonify(annotations)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=56250, debug=True)

