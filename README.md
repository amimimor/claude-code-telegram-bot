# Claude Telegram

A simple Python bridge between Telegram and Claude Code. Control Claude Code remotely via Telegram.

> **Attribution**: This project is inspired by and reimplements the core functionality of [Claude-Code-Remote](https://github.com/anthropics/Claude-Code-Remote), focusing specifically on Telegram integration with a cleaner Python/FastAPI architecture.

## Features

- Send prompts to Claude Code via Telegram
- **Auto-continue conversations** - just reply naturally, no commands needed
- **Quick-reply buttons** for numbered options from Claude
- Markdown responses converted to Telegram HTML formatting
- Continue sessions with `/c` command
- Run compaction with `/compact` command
- Cancel running tasks with `/cancel`
- Hook notifications when Claude completes tasks

### Connection Modes

- **Tunnel mode** (default) - Auto-creates public URL via Cloudflare Tunnel
- **Polling mode** - No public URL needed, polls Telegram API
- **Webhook mode** - Use your own public URL

## Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/claude-telegram.git
cd claude-telegram

# Install with uv
uv sync

# Copy and configure environment
cp .env.example .env
# Edit .env with your Telegram bot token and chat ID
```

### Prerequisites

For **tunnel mode** (default), install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/):

```bash
# macOS
brew install cloudflared

# Linux
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
```

If cloudflared is not available, the app automatically falls back to polling mode.

## Configuration

Create a `.env` file:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Claude Configuration
CLAUDE_CLI_PATH=claude
CLAUDE_WORKING_DIR=/path/to/your/project

# Server
HOST=0.0.0.0
PORT=8000

# Mode: "tunnel" (default), "polling", or "webhook"
MODE=tunnel

# Webhook settings (only if MODE=webhook)
WEBHOOK_URL=https://your-public-url.com
```

### Getting Your Telegram Chat ID

1. Start a chat with your bot
2. Send any message
3. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. Find your `chat.id` in the response

## Usage

### Start the server

```bash
# Tunnel mode (default - auto-creates public URL)
uv run uvicorn claude_telegram.main:app --reload

# Polling mode (no public URL needed)
MODE=polling uv run uvicorn claude_telegram.main:app --reload
```

### Docker

```bash
# Build
docker build -t claude-telegram .

# Run with tunnel (default)
docker run -d \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e TELEGRAM_CHAT_ID=your_chat_id \
  -v /usr/local/bin/claude:/usr/local/bin/claude:ro \
  -v $(pwd):/workspace \
  claude-telegram

# Run with polling
docker run -d \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e TELEGRAM_CHAT_ID=your_chat_id \
  -e MODE=polling \
  -v /usr/local/bin/claude:/usr/local/bin/claude:ro \
  -v $(pwd):/workspace \
  claude-telegram
```

### Docker Compose

```bash
docker-compose up -d
```

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show help |
| `/help` | Show help |
| `/c <message>` | Continue previous session |
| `/new <message>` | Start fresh session |
| `/compact` | Run compaction |
| `/cancel` | Cancel current task |
| `/status` | Check if Claude is running |
| `<any message>` | Auto-continues if recent, else new session |

**Tips:**
- Just type naturally - conversations auto-continue for 10 minutes
- Numbers like "1", "2" auto-continue (for Claude's numbered options)
- Tap inline buttons for quick replies

### Claude Code Hooks

To get notifications when Claude finishes, configure hooks:

**Option 1: Environment variable**
```bash
export CLAUDE_HOOKS_CONFIG=/path/to/claude-telegram/claude-hooks.json
claude
```

**Option 2: Add to `~/.claude/settings.json`**
```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/claude-telegram/hook.py completed",
            "timeout": 30000
          }
        ]
      }
    ]
  }
}
```

## Development

### Run tests

```bash
uv run pytest -v --cov=claude_telegram --cov-report=term-missing
```

### Project structure

```
claude-telegram/
├── src/
│   └── claude_telegram/
│       ├── __init__.py
│       ├── main.py          # FastAPI app & webhook/polling handler
│       ├── config.py        # Settings
│       ├── telegram.py      # Telegram API client
│       ├── claude.py        # Claude Code runner
│       ├── tunnel.py        # Cloudflare Tunnel integration
│       └── markdown.py      # Markdown to Telegram HTML
├── tests/
│   ├── conftest.py          # Pytest fixtures
│   ├── test_main.py         # API tests
│   ├── test_telegram.py     # Telegram service tests
│   ├── test_claude.py       # Claude runner tests
│   └── test_hook.py         # Hook script tests
├── hook.py                  # Claude hook notification script
├── claude-hooks.json        # Hook configuration
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── pyproject.toml
```

## License

MIT
