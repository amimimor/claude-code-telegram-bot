"""FastAPI application - Telegram webhook handler."""

import asyncio
import logging
import random
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request

# Claude-style status messages (like the CLI)
THINKING_MESSAGES = [
    "🧠 <i>Thinking...</i>",
    "💭 <i>Pondering...</i>",
    "🔮 <i>Contemplating...</i>",
    "⚡ <i>Processing...</i>",
    "🎯 <i>Working on it...</i>",
    "✨ <i>Let me think...</i>",
    "🌀 <i>Analyzing...</i>",
    "🔍 <i>Looking into it...</i>",
    "💫 <i>On it...</i>",
    "🎨 <i>Crafting response...</i>",
]

CONTINUE_MESSAGES = [
    "💬 <i>Continuing...</i>",
    "🔄 <i>Picking up where we left off...</i>",
    "📎 <i>Back on it...</i>",
    "🧵 <i>Resuming...</i>",
    "➡️ <i>Moving forward...</i>",
    "🔗 <i>Reconnecting thoughts...</i>",
]

from . import telegram
from .claude import runner
from .config import settings
from .markdown import markdown_to_telegram_html
from .tunnel import tunnel, CloudflareTunnel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Polling state
polling_task: asyncio.Task | None = None
# Current tunnel URL (if using tunnel mode)
tunnel_url: str | None = None

# Conversation state - auto-continue after Claude responds
last_interaction: datetime | None = None
CONVERSATION_TIMEOUT = timedelta(minutes=10)  # Auto-continue window


def is_in_conversation() -> bool:
    """Check if we're in an active conversation (should auto-continue)."""
    if last_interaction is None:
        return False
    return datetime.now() - last_interaction < CONVERSATION_TIMEOUT


def update_conversation():
    """Update the last interaction time."""
    global last_interaction
    last_interaction = datetime.now()


async def poll_updates():
    """Poll Telegram for updates (alternative to webhooks)."""
    offset = 0
    logger.info("Starting polling mode...")

    while True:
        try:
            updates = await telegram.get_updates(offset=offset, timeout=30)

            for update in updates:
                offset = update["update_id"] + 1

                if "message" in update:
                    await handle_message(update["message"])
                elif "callback_query" in update:
                    await handle_callback(update["callback_query"])

        except asyncio.CancelledError:
            logger.info("Polling stopped")
            break
        except Exception as e:
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Setup and teardown."""
    global polling_task, tunnel_url

    mode = settings.mode

    # Tunnel mode (default)
    if mode == "tunnel":
        if not CloudflareTunnel.is_available():
            logger.warning("cloudflared not found, falling back to polling mode")
            mode = "polling"
        else:
            logger.info("Starting Cloudflare tunnel...")
            tunnel.port = settings.port
            tunnel_url = await tunnel.start()

            if tunnel_url:
                webhook_url = f"{tunnel_url}{settings.webhook_path}"
                logger.info(f"Tunnel URL: {tunnel_url}")
                logger.info(f"Setting webhook: {webhook_url}")
                try:
                    await telegram.set_webhook_with_retry(webhook_url)
                    logger.info("Webhook set successfully")
                except Exception as e:
                    logger.error(f"Webhook setup failed after retries: {e}, falling back to polling")
                    mode = "polling"
            else:
                logger.warning("Tunnel failed to start, falling back to polling mode")
                mode = "polling"

    # Manual webhook mode
    if mode == "webhook" and settings.webhook_url:
        webhook_url = f"{settings.webhook_url}{settings.webhook_path}"
        logger.info(f"Setting webhook: {webhook_url}")
        await telegram.set_webhook(webhook_url)

    # Polling mode (fallback)
    if mode == "polling":
        logger.info("Starting polling mode...")
        await telegram.delete_webhook()
        polling_task = asyncio.create_task(poll_updates())

    yield

    # Cleanup
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    if tunnel.is_running:
        await telegram.delete_webhook()
        await tunnel.stop()

    if mode == "webhook" and settings.webhook_url:
        await telegram.delete_webhook()


app = FastAPI(title="Claude Telegram", lifespan=lifespan)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "claude_running": runner.is_running,
        "in_conversation": is_in_conversation(),
    }


@app.post(settings.webhook_path)
async def webhook(request: Request):
    """Handle Telegram webhook updates."""
    data = await request.json()
    logger.info(f"Received update: {data}")

    if "message" in data:
        await handle_message(data["message"])
    elif "callback_query" in data:
        await handle_callback(data["callback_query"])

    return {"ok": True}


async def handle_message(message: dict):
    """Process incoming Telegram message."""
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if not telegram.is_authorized(chat_id):
        logger.warning(f"Unauthorized access from chat_id: {chat_id}")
        return

    if not text:
        return

    # Handle commands
    if text.startswith("/"):
        await handle_command(text, chat_id)
        return

    # Check if it's a quick reply (just a number like "1", "2", "yes", "no")
    quick_reply = is_quick_reply(text)

    # Auto-continue if in conversation, otherwise start new
    continue_session = is_in_conversation() or quick_reply
    await run_claude(text, chat_id, continue_session=continue_session)


def is_quick_reply(text: str) -> bool:
    """Check if the message is a quick reply (number, yes/no, etc.)."""
    text = text.strip().lower()
    # Single number
    if re.match(r"^\d+$", text):
        return True
    # Common quick replies
    if text in ("yes", "no", "y", "n", "ok", "cancel", "skip", "done", "next"):
        return True
    return False


async def handle_command(text: str, chat_id: str):
    """Handle bot commands."""
    cmd = text.split()[0].lower()
    args = text[len(cmd):].strip()

    if cmd == "/start" or cmd == "/help":
        await telegram.send_message(
            "<b>Claude Code</b> via Telegram\n\n"
            "<b>Commands</b>\n"
            "<code>/c &lt;msg&gt;</code> — Continue conversation\n"
            "<code>/new &lt;msg&gt;</code> — Fresh session\n"
            "<code>/compact</code> — Compact context\n"
            "<code>/cancel</code> — Stop current task\n"
            "<code>/status</code> — Check status\n\n"
            "<b>Tips</b>\n"
            "• Just type to chat — auto-continues for 10 min\n"
            "• Numbers (1, 2) and yes/no auto-continue\n"
            "• Tap buttons for quick replies",
            chat_id=chat_id,
            parse_mode="HTML",
        )

    elif cmd == "/c" or cmd == "/continue":
        if args:
            await run_claude(args, chat_id, continue_session=True)
        else:
            await telegram.send_message(
                "Usage: <code>/c &lt;message&gt;</code>",
                chat_id=chat_id,
                parse_mode="HTML",
            )

    elif cmd == "/new":
        if args:
            global last_interaction
            last_interaction = None  # Reset conversation
            await run_claude(args, chat_id, continue_session=False)
        else:
            await telegram.send_message(
                "Usage: <code>/new &lt;message&gt;</code>",
                chat_id=chat_id,
                parse_mode="HTML",
            )

    elif cmd == "/compact":
        if runner.is_running:
            await telegram.send_message(
                "⏳ Claude is busy — use <code>/cancel</code> first",
                chat_id=chat_id,
                parse_mode="HTML",
            )
            return
        await telegram.send_message("🗜 <i>Compacting context...</i>", chat_id=chat_id, parse_mode="HTML")
        result = await runner.compact()
        await send_response(result, chat_id)

    elif cmd == "/cancel":
        if await runner.cancel():
            await telegram.send_message("🛑 Cancelled", chat_id=chat_id, parse_mode="HTML")
        else:
            await telegram.send_message("Nothing to cancel", chat_id=chat_id, parse_mode="HTML")

    elif cmd == "/status":
        if runner.is_running:
            status = "🔄 <b>Running</b>"
        else:
            status = "💤 <b>Idle</b>"
        conv = "active" if is_in_conversation() else "new session"
        await telegram.send_message(
            f"{status} • {conv}",
            chat_id=chat_id,
            parse_mode="HTML",
        )

    else:
        # Unknown command - maybe they meant to chat?
        await telegram.send_message(
            f"Unknown command — try <code>/c {text}</code> to continue",
            chat_id=chat_id,
            parse_mode="HTML",
        )


async def handle_callback(callback: dict):
    """Handle callback query from inline buttons."""
    query_id = callback["id"]
    data = callback.get("data", "")
    chat_id = callback["message"]["chat"]["id"]

    if not telegram.is_authorized(chat_id):
        return

    # Answer the callback to remove loading state
    await telegram.answer_callback(query_id)

    if data.startswith("reply:"):
        reply = data[6:]  # Remove "reply:" prefix
        await run_claude(reply, chat_id, continue_session=True)


async def animate_status(chat_id: str, message_id: int, continue_session: bool):
    """Animate the status message with rotating messages."""
    messages = CONTINUE_MESSAGES if continue_session else THINKING_MESSAGES
    try:
        while True:
            await asyncio.sleep(2.5)  # Update every 2.5 seconds
            new_status = random.choice(messages)
            try:
                await telegram.edit_message(message_id, new_status, chat_id, parse_mode="HTML")
            except Exception:
                pass  # Ignore edit errors (message may be deleted)
    except asyncio.CancelledError:
        pass


async def run_claude(message: str, chat_id: str, continue_session: bool = False):
    """Run Claude and send response to Telegram."""
    if runner.is_running:
        await telegram.send_message(
            "⏳ Claude is busy — use <code>/cancel</code> to stop",
            chat_id=chat_id,
            parse_mode="HTML",
        )
        return

    # Send animated status message
    status_msg = await telegram.send_message(
        random.choice(THINKING_MESSAGES if not continue_session else CONTINUE_MESSAGES),
        chat_id=chat_id,
        parse_mode="HTML",
    )
    message_id = status_msg.get("result", {}).get("message_id")

    # Start animation task
    animation_task = None
    if message_id:
        animation_task = asyncio.create_task(
            animate_status(chat_id, message_id, continue_session)
        )

    try:
        result = await runner.run(message, continue_session=continue_session)
        update_conversation()  # Mark as active conversation

        # Stop animation
        if animation_task:
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass

        # Delete status message and send response
        await telegram.delete_message(chat_id, message_id)
        await send_response(result, chat_id)
    except Exception as e:
        # Stop animation on error
        if animation_task:
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass
        if message_id:
            await telegram.delete_message(chat_id, message_id)

        logger.exception("Claude error")
        await telegram.send_message(
            f"❌ <b>Error:</b> <code>{e}</code>",
            chat_id=chat_id,
            parse_mode="HTML",
        )


async def send_response(text: str, chat_id: str, chunk_size: int = 4000):
    """Send Claude's response, with quick-reply buttons if numbered options detected."""
    if not text.strip():
        await telegram.send_message(
            "<i>(no output)</i>",
            chat_id=chat_id,
            parse_mode="HTML",
        )
        return

    # Detect numbered options before converting to HTML
    buttons = detect_options(text)

    # Convert markdown to Telegram HTML
    html_text = markdown_to_telegram_html(text)

    # Split into chunks if needed
    chunks = split_text(html_text, chunk_size)

    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        reply_markup = buttons if (is_last and buttons) else None
        try:
            await telegram.send_message(
                chunk,
                chat_id=chat_id,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except Exception as e:
            # Fallback to plain text if HTML fails
            logger.warning(f"HTML parse failed, falling back to plain text: {e}")
            await telegram.send_message(
                text if len(chunks) == 1 else chunk,
                chat_id=chat_id,
                parse_mode=None,
                reply_markup=reply_markup,
            )
        if not is_last:
            await asyncio.sleep(0.5)


def detect_options(text: str) -> dict | None:
    """Detect numbered options (1. Option, 2. Option) and create inline keyboard."""
    # Look for patterns like "1.", "2.", "3." at start of lines
    pattern = r"^(\d+)[\.\)]\s+"
    matches = re.findall(pattern, text, re.MULTILINE)

    if not matches or len(matches) < 2:
        return None

    # Get unique numbers, max 8 buttons
    numbers = sorted(set(matches))[:8]

    # Create inline keyboard with number buttons
    buttons = [[{"text": n, "callback_data": f"reply:{n}"} for n in numbers[:4]]]
    if len(numbers) > 4:
        buttons.append([{"text": n, "callback_data": f"reply:{n}"} for n in numbers[4:8]])

    return {"inline_keyboard": buttons}


def split_text(text: str, chunk_size: int) -> list[str]:
    """Split text into chunks, trying to break at newlines."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    current = ""

    for line in text.split("\n"):
        if len(current) + len(line) + 1 > chunk_size:
            if current:
                chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line

    if current:
        chunks.append(current)

    return chunks


@app.post("/notify/{event_type}")
async def notify(event_type: str):
    """Called by Claude hooks to send notifications."""
    if event_type == "completed":
        msg = "✅ Claude has completed the task."
    elif event_type == "waiting":
        msg = "⏸ Claude is waiting for input."
    else:
        msg = f"📢 Claude event: {event_type}"

    await telegram.send_message(msg)
    return {"ok": True}


def main():
    """Run the server."""
    import uvicorn
    uvicorn.run(
        "claude_telegram.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
