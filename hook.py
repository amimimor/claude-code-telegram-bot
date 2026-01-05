#!/usr/bin/env python3
"""
Claude Code hook script.
Called by Claude Code hooks to notify Telegram when tasks complete.

Usage:
    python hook.py completed
    python hook.py waiting

Configure in claude-hooks.json or ~/.claude/settings.json:
{
  "hooks": {
    "Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "python /path/to/hook.py completed"}]}],
    "SubagentStop": [{"matcher": "*", "hooks": [{"type": "command", "command": "python /path/to/hook.py waiting"}]}]
  }
}
"""

import sys
import httpx
from pathlib import Path

# Load .env from script directory
script_dir = Path(__file__).parent
env_file = script_dir / ".env"

if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            import os
            os.environ.setdefault(key.strip(), value.strip())

# Configuration
import os
SERVER_URL = os.getenv("HOOK_SERVER_URL", "http://localhost:8000")


def notify(event_type: str):
    """Send notification to the server."""
    try:
        response = httpx.post(
            f"{SERVER_URL}/notify/{event_type}",
            timeout=10.0,
        )
        response.raise_for_status()
        print(f"Notification sent: {event_type}")
    except Exception as e:
        print(f"Failed to send notification: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python hook.py <completed|waiting>", file=sys.stderr)
        sys.exit(1)

    event_type = sys.argv[1]
    notify(event_type)
