#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "=== Starting light-server (local mode, no Docker) ==="
light-server serve --config server.yaml &
SERVER_PID=$!

# Wait for server to be ready
sleep 3

echo ""
echo "=== Inference ==="
curl -s -X POST http://127.0.0.1:8000/v2/models/demo_model/infer \
  -H "Content-Type: application/json" \
  -d '{"text": "This is a great and amazing product"}' | python3 -m json.tool

echo ""
echo "=== Metrics ==="
curl -s http://127.0.0.1:8002/metrics | grep demo_model || echo "(no metrics yet)"

echo ""
echo "=== Stopping server ==="
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo "Done."
