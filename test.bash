bash
curl <http://localhost:11434/api/generate> \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "qwen3-vl:2b",
    "prompt": "What is in this image? Describe it in detail.",
    "images": ["base64_encoded_image_data_here"]
  }'