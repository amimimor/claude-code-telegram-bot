"""Tests for Telegram service."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

# Import after setting env vars in conftest
from claude_telegram import telegram


@pytest.mark.asyncio
async def test_send_message_success(mock_httpx):
    """Test successful message sending."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 123}}
    mock_response.raise_for_status = MagicMock()
    mock_httpx.post = AsyncMock(return_value=mock_response)

    result = await telegram.send_message("Hello", chat_id="12345")

    assert result["ok"] is True
    mock_httpx.post.assert_called_once()
    call_args = mock_httpx.post.call_args
    assert "sendMessage" in call_args[0][0]
    assert call_args[1]["json"]["text"] == "Hello"
    assert call_args[1]["json"]["chat_id"] == "12345"


@pytest.mark.asyncio
async def test_send_message_with_reply_markup(mock_httpx):
    """Test message with inline keyboard."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True}
    mock_response.raise_for_status = MagicMock()
    mock_httpx.post = AsyncMock(return_value=mock_response)

    markup = {"inline_keyboard": [[{"text": "Button", "callback_data": "test"}]]}
    await telegram.send_message("Choose:", reply_markup=markup)

    call_args = mock_httpx.post.call_args
    assert call_args[1]["json"]["reply_markup"] == markup


@pytest.mark.asyncio
async def test_send_message_http_error(mock_httpx):
    """Test handling of HTTP errors."""
    mock_httpx.post = AsyncMock(side_effect=httpx.HTTPStatusError(
        "Error", request=MagicMock(), response=MagicMock(status_code=400)
    ))

    with pytest.raises(httpx.HTTPStatusError):
        await telegram.send_message("Hello")


@pytest.mark.asyncio
async def test_edit_message_success(mock_httpx):
    """Test successful message editing."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True}
    mock_response.raise_for_status = MagicMock()
    mock_httpx.post = AsyncMock(return_value=mock_response)

    result = await telegram.edit_message(123, "Updated text", chat_id="12345")

    assert result["ok"] is True
    call_args = mock_httpx.post.call_args
    assert "editMessageText" in call_args[0][0]
    assert call_args[1]["json"]["message_id"] == 123
    assert call_args[1]["json"]["text"] == "Updated text"


@pytest.mark.asyncio
async def test_set_webhook(mock_httpx):
    """Test webhook setup."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True}
    mock_response.raise_for_status = MagicMock()
    mock_httpx.post = AsyncMock(return_value=mock_response)

    result = await telegram.set_webhook("https://example.com/webhook")

    assert result["ok"] is True
    call_args = mock_httpx.post.call_args
    assert "setWebhook" in call_args[0][0]
    assert call_args[1]["json"]["url"] == "https://example.com/webhook"


@pytest.mark.asyncio
async def test_delete_webhook(mock_httpx):
    """Test webhook deletion."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True}
    mock_response.raise_for_status = MagicMock()
    mock_httpx.post = AsyncMock(return_value=mock_response)

    result = await telegram.delete_webhook()

    assert result["ok"] is True
    call_args = mock_httpx.post.call_args
    assert "deleteWebhook" in call_args[0][0]


def test_is_authorized_valid():
    """Test authorization with valid chat ID."""
    assert telegram.is_authorized(12345) is True
    assert telegram.is_authorized("12345") is True


def test_is_authorized_invalid():
    """Test authorization with invalid chat ID."""
    assert telegram.is_authorized(99999) is False
    assert telegram.is_authorized("invalid") is False
