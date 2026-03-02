from ollama import Client
client = Client(
  host='http://192.168.191.130:11434',
  headers={'x-some-header': 'some-value'}
)
response = client.chat(model='qwen3-vl:8b', messages=[
  {
    'role': 'user',
    'content': 'Why is the sky blue?',
  },
])

print(response)