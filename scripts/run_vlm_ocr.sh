curl -sS -H "Content-Type: application/json" -d '{
  "file_ids": ["95e4472b-f848-456a-9c49-ae1de2ff0d59"],
  "name": "vlm_ocr",
  "params": {}
}' http://localhost:8000/files:run