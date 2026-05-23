#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "=== Starting light-server ==="
light-server serve --config server.yaml &
SERVER_PID=$!

# Wait for server to be ready
sleep 3

echo ""
echo "=== Running WebSocket streaming client ==="
python client.py

echo ""
echo "=== Stopping server ==="
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo "Done."
