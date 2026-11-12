#!/bin/bash
set -e

echo "=== ClipCannon Starting ==="
echo "GPU Status:"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || echo "No GPU detected"
echo ""

# Start dashboard
echo "Starting Dashboard on port 3200..."
python -m clipcannon.dashboard.app &
DASH_PID=$!

echo ""
echo "=== ClipCannon Ready ==="
echo "  Dashboard:      http://localhost:3200"
echo "  MCP Server:      stdio (connect via claude mcp add)"
echo ""

# Wait for the dashboard to exit and propagate its status
wait $DASH_PID
exit $?
