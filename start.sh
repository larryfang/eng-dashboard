#!/bin/bash
# Engineering Director Dashboard — Start Script
set -e
cd "$(dirname "$0")"

# Check for organization config (legacy or domain-based)
has_config=false
[ -f "config/organization.yaml" ] && has_config=true
ls config/domains/*.yaml >/dev/null 2>&1 && has_config=true

if [ "$has_config" = false ]; then
  echo ""
  echo "============================================================"
  echo "  No config found (checked config/organization.yaml and"
  echo "  config/domains/*.yaml)."
  echo "  The setup wizard will guide you through configuration."
  echo ""
  echo "  Option A: Run the wizard (recommended)"
  echo "    → Open http://localhost:5173 after startup"
  echo ""
  echo "  Option B: Copy the example config manually"
  echo "    cp config/organization.example.yaml config/organization.yaml"
  echo "    cp .env.example .env"
  echo "    # Then edit both files with your details"
  echo "============================================================"
  echo ""
fi

# Check for .env
if [ ! -f ".env" ]; then
  echo "Note: No .env file found. Copy .env.example to .env and add your tokens."
  echo ""
fi

# Verify uv is installed
if ! command -v uv &> /dev/null; then
  echo "Error: 'uv' is not installed."
  echo "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# Verify Node.js / npm is installed
if ! command -v npm &> /dev/null; then
  echo "Error: 'npm' is not installed. Install Node.js from https://nodejs.org"
  exit 1
fi

# Install frontend dependencies if needed
if [ -d "frontend" ] && [ ! -d "frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  cd frontend && npm install && cd ..
fi

echo "Starting Engineering Director Dashboard..."
echo "  Backend:  http://localhost:9001"
echo "  Frontend: http://localhost:5173"
echo ""

# Start backend from project root so "backend.*" is the only valid import path
(uv run uvicorn backend.main:app --host 0.0.0.0 --port 9001 --reload 2>&1 | sed 's/^/[backend] /') &
BACKEND_PID=$!

# Start frontend if it exists
if [ -d "frontend" ]; then
  (cd frontend && npm run dev 2>&1 | sed 's/^/[frontend] /') &
  FRONTEND_PID=$!
fi

# Open browser after a short delay
sleep 2
if command -v open &> /dev/null; then
  open http://localhost:5173
elif command -v xdg-open &> /dev/null; then
  xdg-open http://localhost:5173
fi

# Wait for Ctrl+C and clean up
trap 'echo "Stopping..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit' INT TERM
wait
