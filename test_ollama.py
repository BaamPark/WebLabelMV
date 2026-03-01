import cv2
import numpy as np
from ollama import chat

frame = cv2.imread("sample_scene.png")  # or frame from video

# Convert BGR → RGB (important)
frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

# Encode to PNG bytes
_, buffer = cv2.imencode(".png", frame_rgb)
image_bytes = buffer.tobytes()

response = chat(
    model="qwen3-vl:2b",
    messages=[
        {
            "role": "user",
            "content": "localize all the people in the image with a format of (x1,y1), (x2,y2) using json format",
            "images": [image_bytes],
        }
    ],
)

print(response["message"]["content"])