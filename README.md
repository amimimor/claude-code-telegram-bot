# Claude Telegram

Control Claude Code remotely via Telegram. A Python/FastAPI bridge that lets you interact with Claude Code from anywhere.

> **Attribution**: Inspired by [Claude-Code-Remote](https://github.com/anthropics/Claude-Code-Remote), reimplemented with a cleaner Python architecture.

## Features

- **Multi-session support** - Run Claude in different directories simultaneously
- **Animated status messages** - Rotating "Thinking...", "Pondering..." etc. while Claude works
- **Auto-continue conversations** - Just reply naturally, no commands needed
- **Quick-reply buttons** - Tap numbered options directly
- **Markdown rendering** - Claude's markdown converted to Telegram HTML
- **Smart session handling** - 10-minute auto-continue window per session
- **Three connection modes** - Tunnel (default), Polling, or Webhook

## Quick Start

### 1. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Choose a name (e.g., "My Claude Bot")
4. Choose a username (must end in `bot`, e.g., `my_claude_bot`)
5. **Save the bot token** - looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### 2. Get Your Chat ID

1. Start a chat with your new bot (search for it by username)
2. Send any message to it (e.g., "hello")
3. Open this URL in your browser (replace `YOUR_BOT_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
4. Find `"chat":{"id":` in the response - that number is your chat ID
   - Example: `"chat":{"id":123456789` → your chat ID is `123456789`

### 3. Install Prerequisites

```bash
# Clone the repo
git clone https://github.com/yourusername/claude-telegram.git
cd claude-telegram

# Install Python dependencies
uv sync

# Install cloudflared (for tunnel mode)
# macOS:
brew install cloudflared

# Linux:
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
CLAUDE_CLI_PATH=claude
CLAUDE_WORKING_DIR=/path/to/your/project
MODE=tunnel
```

### 5. Run

```bash
uv run uvicorn claude_telegram.main:app --host 0.0.0.0 --port 8000
```

You should see:
```
Starting Cloudflare tunnel...
Tunnel started: https://random-words.trycloudflare.com
Setting webhook...
Webhook set successfully
Application startup complete.
```

Now send a message to your bot!

## Connection Modes

### Tunnel Mode (Default)

Uses Cloudflare's free quick tunnels to create a public URL automatically.

**Note: DNS Propagation** - When the tunnel starts, it may take 2-5 minutes for the DNS to propagate globally. The app will automatically retry the webhook setup with exponential backoff. You'll see retry messages in the logs - this is normal. Once DNS propagates, you'll see "Webhook set successfully".

```bash
MODE=tunnel uv run uvicorn claude_telegram.main:app
```

### Polling Mode

No public URL needed - polls Telegram's servers directly. Slightly higher latency but simpler setup.

```bash
MODE=polling uv run uvicorn claude_telegram.main:app
```

### Webhook Mode

Use your own public URL (e.g., behind nginx, Caddy, or a cloud provider).

```bash
MODE=webhook WEBHOOK_URL=https://your-domain.com uv run uvicorn claude_telegram.main:app
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start`, `/help` | Show help with formatted commands |
| `/c <message>` | Continue previous session |
| `/new <message>` | Start fresh session (reset context) |
| `/dir <path>` | Switch to a different directory/session |
| `/dirs` | List all active sessions |
| `/compact` | Compact conversation context |
| `/cancel` | Cancel current running task |
| `/status` | Check if Claude is running |
| `<any text>` | Auto-continues if within 10 min, else new session |

**Tips:**
- Just type naturally - conversations auto-continue for 10 minutes
- Quick replies like "1", "2", "yes", "no" always continue
- Tap inline buttons for numbered options
- Use `/dir ~/projects/foo` to switch directories and run Claude there

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | (required) | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | (required) | Your chat ID (security: only this chat can use the bot) |
| `CLAUDE_CLI_PATH` | `claude` | Path to Claude CLI |
| `CLAUDE_WORKING_DIR` | (none) | Working directory for Claude |
| `MODE` | `tunnel` | `tunnel`, `polling`, or `webhook` |
| `HOST` | `0.0.0.0` | Server host |
| `PORT` | `8000` | Server port |
| `WEBHOOK_URL` | (none) | Your public URL (webhook mode only) |

## Docker

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

## Claude Code Hooks

Get notified in Telegram when Claude finishes:

**Option 1: Environment variable**
```bash
export CLAUDE_HOOKS_CONFIG=/path/to/claude-telegram/claude-hooks.json
claude
```

**Option 2: Add to `~/.claude/settings.json`**
```json
{
  "hooks": {
    "Stop": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "python /path/to/claude-telegram/hook.py completed",
        "timeout": 30000
      }]
    }]
  }
}
```

## Troubleshooting

### "Webhook setup failed" / DNS errors

This is normal for tunnel mode! Cloudflare quick tunnels take 2-5 minutes for DNS to propagate globally. The app retries automatically with exponential backoff (up to 15 attempts). Just wait.

### Bot doesn't respond

1. Check the chat ID matches your `.env`
2. Make sure you messaged the bot first (it can't initiate)
3. Check server logs for errors

### "Claude is busy"

Claude is still processing. Use `/cancel` to stop it, or wait.

## Development

```bash
# Run tests
uv run pytest -v --cov=claude_telegram

# Run with reload
uv run uvicorn claude_telegram.main:app --reload
```

## Project Structure

```
claude-telegram/
├── src/claude_telegram/
│   ├── main.py          # FastAPI app, webhook/polling handlers
│   ├── config.py        # Pydantic settings
│   ├── telegram.py      # Telegram API client
│   ├── claude.py        # Claude CLI runner
│   ├── tunnel.py        # Cloudflare Tunnel manager
│   └── markdown.py      # MD → Telegram HTML
├── tests/               # Pytest tests
├── hook.py              # Hook notification script
├── Dockerfile
└── docker-compose.yml
```

## License

MIT
