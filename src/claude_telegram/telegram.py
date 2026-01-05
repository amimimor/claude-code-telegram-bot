"""Telegram bot service."""

import logging

import httpx

from .config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


async def send_message(
    text: str,
    chat_id: str | None = None,
    parse_mode: str = "Markdown",
    reply_markup: dict | None = None,
) -> dict:
    """Send a message to Telegram."""
    chat_id = chat_id or settings.telegram_chat_id

    # Telegram requires non-empty text
    if not text or not text.strip():
        text = "(empty)"

    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    # Only add parse_mode if specified (can cause issues with special chars)
    if parse_mode:
        payload["parse_mode"] = parse_mode

    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        if response.status_code != 200:
            logger.error(f"Telegram error: {response.status_code} - {response.text}")
        response.raise_for_status()
        return response.json()


async def edit_message(
    message_id: int,
    text: str,
    chat_id: str | None = None,
    parse_mode: str = "Markdown",
) -> dict:
    """Edit an existing message."""
    chat_id = chat_id or settings.telegram_chat_id

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{TELEGRAM_API}/editMessageText", json=payload)
        response.raise_for_status()
        return response.json()


async def set_webhook(url: str) -> dict:
    """Set the Telegram webhook URL."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": url, "allowed_updates": ["message", "callback_query"]},
        )
        response.raise_for_status()
        return response.json()


async def delete_webhook() -> dict:
    """Delete the Telegram webhook."""
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{TELEGRAM_API}/deleteWebhook")
        response.raise_for_status()
        return response.json()


async def get_updates(offset: int = 0, timeout: int = 30) -> list[dict]:
    """Get updates using long polling."""
    async with httpx.AsyncClient(timeout=timeout + 10) as client:
        response = await client.post(
            f"{TELEGRAM_API}/getUpdates",
            json={
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["message", "callback_query"],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("result", [])


async def answer_callback(callback_query_id: str, text: str | None = None) -> dict:
    """Answer a callback query (inline button press)."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload)
        response.raise_for_status()
        return response.json()


def is_authorized(chat_id: str | int) -> bool:
    """Check if the chat is authorized."""
    return str(chat_id) == str(settings.telegram_chat_id)
