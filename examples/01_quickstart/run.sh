#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "=== Starting light-server ==="
light-server serve --config server.yaml &
SERVER_PID=$!

# Wait for server to be ready
sleep 3

echo ""
echo "=== Single inference ==="
curl -s -X POST http://127.0.0.1:8000/v2/models/echo_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": "hello world"}' | python3 -m json.tool

echo ""
echo "=== List loaded models ==="
curl -s http://127.0.0.1:8000/v2/models | python3 -m json.tool

echo ""
echo "=== Check readiness ==="
curl -s http://127.0.0.1:8000/v2/models/echo_model/ready | python3 -m json.tool

echo ""
echo "=== Stopping server ==="
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo "Done."
