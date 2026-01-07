"""FastAPI application - Telegram webhook handler."""

import asyncio
import logging
import random
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request

# Claude Code spinner words (from the CLI)
# Source: https://github.com/levindixon/tengu_spinner_words
SPINNER_VERBS = [
    "Accomplishing", "Actioning", "Actualizing", "Baking", "Booping", "Brewing",
    "Calculating", "Cerebrating", "Channelling", "Churning", "Clauding", "Coalescing",
    "Cogitating", "Combobulating", "Computing", "Concocting", "Conjuring", "Considering",
    "Contemplating", "Cooking", "Crafting", "Creating", "Crunching", "Deciphering",
    "Deliberating", "Determining", "Discombobulating", "Divining", "Doing", "Effecting",
    "Elucidating", "Enchanting", "Envisioning", "Finagling", "Flibbertigibbeting",
    "Forging", "Forming", "Frolicking", "Generating", "Germinating", "Hatching",
    "Herding", "Honking", "Hustling", "Ideating", "Imagining", "Incubating", "Inferring",
    "Jiving", "Manifesting", "Marinating", "Meandering", "Moseying", "Mulling",
    "Mustering", "Musing", "Noodling", "Percolating", "Perusing", "Philosophising",
    "Pondering", "Pontificating", "Processing", "Puttering", "Puzzling", "Reticulating",
    "Ruminating", "Scheming", "Schlepping", "Shimmying", "Shucking", "Simmering",
    "Smooshing", "Spelunking", "Spinning", "Stewing", "Sussing", "Synthesizing",
    "Thinking", "Tinkering", "Transmuting", "Unfurling", "Unravelling", "Vibing",
    "Wandering", "Whirring", "Wibbling", "Wizarding", "Working", "Wrangling",
]

def get_thinking_message() -> str:
    """Get a random thinking message with emoji."""
    verb = random.choice(SPINNER_VERBS)
    return f"✨ <i>{verb}...</i>"

def get_continue_message() -> str:
    """Get a random continue message with emoji."""
    verb = random.choice(SPINNER_VERBS)
    return f"🔄 <i>{verb}...</i>"

from . import telegram
from .claude import sessions, ClaudeResult, PermissionDenial
from .config import settings
from .markdown import markdown_to_telegram_html
from .tunnel import tunnel, CloudflareTunnel

# Store pending permission requests for retry
pending_permissions: dict[str, dict] = {}  # chat_id -> {message, denials, session_key}

# Helper to get current runner
def get_runner():
    """Get the current session's runner."""
    return sessions.get_current_session()


def build_session_buttons(session_list: list, current) -> dict:
    """Build inline keyboard buttons for session selection."""
    buttons = []
    row = []
    for i, (dir_key, session) in enumerate(session_list, 1):
        # Mark current session with checkmark
        label = f"{'✓ ' if session == current else ''}{i}. {session.short_name}"
        row.append({"text": label, "callback_data": f"dir:{dir_key}"})
        # Max 2 buttons per row
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return {"inline_keyboard": buttons}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Polling state
polling_task: asyncio.Task | None = None
# Current tunnel URL (if using tunnel mode)
tunnel_url: str | None = None


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
    current = sessions.get_current_session()
    return {
        "status": "ok",
        "claude_running": sessions.any_running(),
        "current_session": current.short_name,
        "in_conversation": current.is_in_conversation(),
        "active_sessions": len(sessions.sessions),
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

    # Auto-continue if current session is in conversation
    current = sessions.get_current_session()
    continue_session = current.is_in_conversation() or quick_reply
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
            "<code>/dir path</code> — Switch directory (relative to ~)\n"
            "<code>/dirs</code> — List sessions + buttons\n"
            "<code>/compact</code> — Compact context\n"
            "<code>/cancel</code> — Stop current task\n"
            "<code>/status</code> — Check status\n\n"
            "<b>Tips</b>\n"
            "• Just type to chat — auto-continues for 10 min\n"
            "• <code>/dir projects/foo</code> = ~/projects/foo\n"
            "• Tap buttons in /dirs to switch",
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
            # Reset current session's conversation state
            runner = get_runner()
            runner.last_interaction = None
            await run_claude(args, chat_id, continue_session=False)
        else:
            await telegram.send_message(
                "Usage: <code>/new &lt;message&gt;</code>",
                chat_id=chat_id,
                parse_mode="HTML",
            )

    elif cmd == "/dir":
        if args:
            session = sessions.switch_session(args)
            status = "🔄 running" if session.is_running else "💤 idle"
            conv = "in conversation" if session.is_in_conversation() else "fresh"

            # Check for stored session context
            context = None
            if not session.context_shown and not session.is_in_conversation():
                context = session.get_session_context()

            msg = f"📂 Switched to <code>{session.short_name}</code>\nStatus: {status} • {conv}"
            if context:
                msg += f"\n\n📜 <b>Previous context:</b>\n<i>{context}</i>"

            await telegram.send_message(
                msg,
                chat_id=chat_id,
                parse_mode="HTML",
            )
        else:
            # Show session picker if sessions exist
            session_list = sessions.list_sessions()
            current = get_runner()
            if len(session_list) > 1:
                buttons = build_session_buttons(session_list, current)
                await telegram.send_message(
                    f"📂 Current: <code>{current.short_name}</code>\n\n"
                    "Select or add new: <code>/dir projects/foo</code>\n"
                    "<i>(paths are relative to home)</i>",
                    chat_id=chat_id,
                    parse_mode="HTML",
                    reply_markup=buttons,
                )
            else:
                await telegram.send_message(
                    f"📂 Current: <code>{current.short_name}</code>\n\n"
                    "Usage: <code>/dir projects/foo</code>\n"
                    "<i>(paths are relative to home)</i>",
                    chat_id=chat_id,
                    parse_mode="HTML",
                )

    elif cmd == "/dirs":
        session_list = sessions.list_sessions()
        if not session_list:
            await telegram.send_message(
                "No active sessions",
                chat_id=chat_id,
                parse_mode="HTML",
            )
        else:
            current = get_runner()
            lines = ["<b>Active Sessions</b>\n"]
            for i, (dir_key, session) in enumerate(session_list, 1):
                marker = "→ " if session == current else "  "
                status = "🔄" if session.is_running else "💤"
                lines.append(f"{marker}{i}. {status} <code>{session.short_name}</code>")
            buttons = build_session_buttons(session_list, current)
            await telegram.send_message(
                "\n".join(lines),
                chat_id=chat_id,
                parse_mode="HTML",
                reply_markup=buttons,
            )

    elif cmd == "/compact":
        runner = get_runner()
        if runner.is_running:
            await telegram.send_message(
                "⏳ Claude is busy — use <code>/cancel</code> first",
                chat_id=chat_id,
                parse_mode="HTML",
            )
            return
        await telegram.send_message(
            f"🗜 <i>Compacting context for {runner.short_name}...</i>",
            chat_id=chat_id,
            parse_mode="HTML",
        )
        result = await runner.compact()
        await send_response(result.text, chat_id)

    elif cmd == "/cancel":
        runner = get_runner()
        if await runner.cancel():
            await telegram.send_message(
                f"🛑 Cancelled <code>{runner.short_name}</code>",
                chat_id=chat_id,
                parse_mode="HTML",
            )
        else:
            await telegram.send_message("Nothing to cancel", chat_id=chat_id, parse_mode="HTML")

    elif cmd == "/status":
        runner = get_runner()
        if runner.is_running:
            status = "🔄 <b>Running</b>"
        else:
            status = "💤 <b>Idle</b>"
        conv = "in conversation" if runner.is_in_conversation() else "new session"
        await telegram.send_message(
            f"📂 <code>{runner.short_name}</code>\n{status} • {conv}",
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

    elif data.startswith("dir:"):
        dir_path = data[4:]  # Remove "dir:" prefix
        session = sessions.switch_session(dir_path)
        status = "🔄 running" if session.is_running else "💤 idle"
        conv = "in conversation" if session.is_in_conversation() else "fresh"

        # Check for stored session context
        context = None
        if not session.context_shown and not session.is_in_conversation():
            context = session.get_session_context()

        msg = f"📂 Switched to <code>{session.short_name}</code>\nStatus: {status} • {conv}"
        if context:
            msg += f"\n\n📜 <b>Previous context:</b>\n<i>{context}</i>"

        await telegram.send_message(
            msg,
            chat_id=chat_id,
            parse_mode="HTML",
        )

    elif data == "perm:allow":
        # User approved the permission request - retry with allowed tools
        pending = pending_permissions.get(str(chat_id))
        if not pending:
            await telegram.send_message(
                "No pending permission request.",
                chat_id=chat_id,
                parse_mode="HTML",
            )
            return

        # Build allowed tools list from denials
        allowed_tools = []
        for denial in pending["denials"]:
            tool = denial.tool_name
            tool_input = denial.tool_input
            if tool == "Write":
                path = tool_input.get("file_path", "")
                allowed_tools.append(f"Write:{path}")
            elif tool == "Edit":
                path = tool_input.get("file_path", "")
                allowed_tools.append(f"Edit:{path}")
            elif tool == "Read":
                path = tool_input.get("file_path", "")
                allowed_tools.append(f"Read:{path}")
            elif tool == "Bash":
                cmd = tool_input.get("command", "")
                # Allow the specific command
                allowed_tools.append(f"Bash:{cmd}")
            else:
                allowed_tools.append(tool)

        # Clear pending and retry
        original_message = pending["message"]
        del pending_permissions[str(chat_id)]

        await telegram.send_message(
            f"✅ <i>Retrying with permissions...</i>",
            chat_id=chat_id,
            parse_mode="HTML",
        )

        await run_claude(
            original_message,
            chat_id,
            continue_session=True,
            allowed_tools=allowed_tools,
        )

    elif data == "perm:deny":
        # User denied - just clear the pending request
        if str(chat_id) in pending_permissions:
            del pending_permissions[str(chat_id)]
        await telegram.send_message(
            "❌ Permission denied. Request cancelled.",
            chat_id=chat_id,
            parse_mode="HTML",
        )


async def animate_status(chat_id: str, message_id: int, continue_session: bool, session_name: str):
    """Animate the status message with rotating messages."""
    prefix = f"[<code>{session_name}</code>] " if session_name != "default" else ""
    try:
        while True:
            await asyncio.sleep(2.5)  # Update every 2.5 seconds
            status = get_continue_message() if continue_session else get_thinking_message()
            new_status = f"{prefix}{status}"
            try:
                await telegram.edit_message(message_id, new_status, chat_id, parse_mode="HTML")
            except Exception:
                pass  # Ignore edit errors (message may be deleted)
    except asyncio.CancelledError:
        pass


async def run_claude(
    message: str,
    chat_id: str,
    continue_session: bool = False,
    allowed_tools: list[str] | None = None,
):
    """Run Claude and send response to Telegram."""
    runner = get_runner()
    session_name = runner.short_name
    prefix = f"[<code>{session_name}</code>] " if session_name != "default" else ""

    if runner.is_running:
        await telegram.send_message(
            f"{prefix}⏳ Claude is busy — use <code>/cancel</code> to stop",
            chat_id=chat_id,
            parse_mode="HTML",
        )
        return

    # Check for stored session context on first interaction
    if not runner.context_shown and not runner.is_in_conversation():
        context = runner.get_session_context()
        if context:
            await telegram.send_message(
                f"{prefix}📜 <b>Resuming previous session:</b>\n<i>{context}</i>",
                chat_id=chat_id,
                parse_mode="HTML",
            )

    # Send animated status message
    initial_status = get_continue_message() if continue_session else get_thinking_message()
    status_msg = await telegram.send_message(
        f"{prefix}{initial_status}",
        chat_id=chat_id,
        parse_mode="HTML",
    )
    message_id = status_msg.get("result", {}).get("message_id")

    # Start animation task
    animation_task = None
    if message_id:
        animation_task = asyncio.create_task(
            animate_status(chat_id, message_id, continue_session, session_name)
        )

    try:
        result = await runner.run(
            message,
            continue_session=continue_session,
            allowed_tools=allowed_tools,
        )

        # Stop animation
        if animation_task:
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass

        # Delete status message
        await telegram.delete_message(chat_id, message_id)

        # Check for permission denials
        if result.permission_denials:
            await send_permission_request(
                result, message, chat_id, session_name, sessions.current_dir
            )
        else:
            await send_response(result.text, chat_id, session_name=session_name)

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
            f"{prefix}❌ <b>Error:</b> <code>{e}</code>",
            chat_id=chat_id,
            parse_mode="HTML",
        )


async def send_permission_request(
    result: ClaudeResult,
    original_message: str,
    chat_id: str,
    session_name: str,
    session_dir: str,
):
    """Send permission denial info to user with Allow/Deny buttons."""
    prefix = f"[<code>{session_name}</code>] " if session_name != "default" else ""

    # Format the denied permissions
    denial_lines = []
    for d in result.permission_denials:
        tool = d.tool_name
        if tool == "Write":
            path = d.tool_input.get("file_path", "unknown")
            denial_lines.append(f"• <b>Write</b> to <code>{path}</code>")
        elif tool == "Bash":
            cmd = d.tool_input.get("command", "unknown")[:60]
            denial_lines.append(f"• <b>Bash</b>: <code>{cmd}</code>")
        elif tool == "Edit":
            path = d.tool_input.get("file_path", "unknown")
            denial_lines.append(f"• <b>Edit</b> <code>{path}</code>")
        elif tool == "Read":
            path = d.tool_input.get("file_path", "unknown")
            denial_lines.append(f"• <b>Read</b> <code>{path}</code>")
        else:
            denial_lines.append(f"• <b>{tool}</b>: {str(d.tool_input)[:50]}")

    # Store pending request for retry
    pending_permissions[str(chat_id)] = {
        "message": original_message,
        "denials": result.permission_denials,
        "session_dir": session_dir,
    }

    # Build message with buttons
    msg = (
        f"{prefix}⚠️ <b>Permission denied:</b>\n"
        + "\n".join(denial_lines)
    )

    # Also show partial result if any
    if result.text.strip():
        msg += f"\n\n<i>{result.text[:500]}</i>"

    buttons = {
        "inline_keyboard": [
            [
                {"text": "✅ Allow & Retry", "callback_data": "perm:allow"},
                {"text": "❌ Deny", "callback_data": "perm:deny"},
            ]
        ]
    }

    await telegram.send_message(
        msg,
        chat_id=chat_id,
        parse_mode="HTML",
        reply_markup=buttons,
    )


async def send_response(text: str, chat_id: str, chunk_size: int = 4000, session_name: str = "default"):
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


@app.post("/test")
async def test_message(request: Request):
    """Test endpoint - send a message as if from Telegram."""
    data = await request.json()
    text = data.get("text", "")
    chat_id = str(settings.telegram_chat_id)

    if not text:
        return {"error": "No text provided"}

    # Handle as if it's a Telegram message
    if text.startswith("/"):
        await handle_command(text, chat_id)
    else:
        current = sessions.get_current_session()
        continue_session = current.is_in_conversation()
        await run_claude(text, chat_id, continue_session=continue_session)

    return {"ok": True, "text": text}


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
