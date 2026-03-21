#!/bin/bash
set -e

echo "=== ClipCannon Starting ==="
echo "GPU Status:"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || echo "No GPU detected"
echo ""

# Start license server in background
echo "Starting License Server on port 3100..."
python -m uvicorn license_server.server:app --host 0.0.0.0 --port 3100 &
LICENSE_PID=$!

# Start dashboard
echo "Starting Dashboard on port 3200..."
python -m clipcannon.dashboard.app &
DASH_PID=$!

echo ""
echo "=== ClipCannon Ready ==="
echo "  Dashboard:      http://localhost:3200"
echo "  License Server:  http://localhost:3100"
echo "  MCP Server:      stdio (connect via claude mcp add)"
echo ""

# Wait for any process to exit
wait -n $LICENSE_PID $DASH_PID

# Exit with status of process that exited first
exit $?
