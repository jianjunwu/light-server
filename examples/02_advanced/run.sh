#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "=== Starting light-server ==="
light-server serve --config server.yaml &
SERVER_PID=$!

# Wait for server to be ready
sleep 3

echo ""
echo "=== Single inference (v1, multiply by 2) ==="
curl -s -X POST http://127.0.0.1:8000/v2/models/advanced_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": 5}' | python3 -m json.tool

echo ""
echo "=== Batch inference (4 parallel requests) ==="
for i in 1 2 3 4; do
  curl -s -X POST http://127.0.0.1:8000/v2/models/advanced_model/infer \
    -H "Content-Type: application/json" \
    -d "{\"input\": $i}" &
done
wait
echo ""

echo "=== Prometheus metrics ==="
curl -s http://127.0.0.1:8002/metrics | grep advanced_model || echo "(no metrics yet)"

echo ""
echo "=== Switch to v2 (add 100) ==="
curl -s -X POST http://127.0.0.1:8000/v2/repository/models/advanced_model/load \
  -H "Content-Type: application/json" \
  -d '{"version": "2"}' | python3 -m json.tool

echo ""
echo "=== Inference after version switch ==="
curl -s -X POST http://127.0.0.1:8000/v2/models/advanced_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": 5}' | python3 -m json.tool

echo ""
echo "=== Stopping server ==="
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo "Done."
