#!/bin/bash
set -e

# The app handles tunnel/polling/webhook mode internally
# Just start the FastAPI server
echo "Starting Claude Telegram server (mode: ${MODE:-tunnel})..."
exec uv run uvicorn claude_telegram.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}
