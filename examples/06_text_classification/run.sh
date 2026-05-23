#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "=== Testing model logic (no server needed) ==="
python test_model.py

echo ""
echo "=== Starting light-server ==="
light-server serve --config server.yaml &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for server to start..."
sleep 5

echo ""
echo "=== Running HTTP client ==="
python client.py

echo ""
echo "=== Stopping server ==="
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo "Done."
