#!/bin/bash
set -euo pipefail

echo "=== ClipCannon Setup ==="
echo ""

# Create virtual environment if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Installing core dependencies..."
pip install -e .

echo ""
echo "Installing ML dependencies (large, may take a while)..."
pip install -e ".[ml]" || echo "WARNING: Some ML dependencies failed to install. GPU-dependent pipeline stages may not work."

echo ""
echo "Installing dev dependencies..."
pip install -e ".[dev]"

echo ""
echo "Creating ClipCannon directories..."
mkdir -p ~/.clipcannon/projects ~/.clipcannon/models ~/.clipcannon/tmp

echo ""
echo "Copying default config..."
cp -n config/default_config.json ~/.clipcannon/config.json 2>/dev/null || true

echo ""
echo "=== Setup Complete ==="
echo "  Run 'clipcannon' to start the MCP server"
echo "  Run 'python -m clipcannon.dashboard.app' to start the dashboard"
echo "  Run 'scripts/validate_gpu.py' to check GPU status"
echo "  Run 'scripts/download_models.py' to download ML models"
