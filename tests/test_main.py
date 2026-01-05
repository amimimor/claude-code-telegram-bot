"""Tests for FastAPI main application."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

# Must patch before importing app
with patch.dict("os.environ", {
    "TELEGRAM_BOT_TOKEN": "test_token",
    "TELEGRAM_CHAT_ID": "12345",
}):
    from claude_telegram.main import app, handle_message, handle_command, run_claude, send_response


client = TestClient(app)


def test_health_check():
    """Test health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "claude_running" in data


def test_webhook_empty_update():
    """Test webhook with empty update."""
    response = client.post("/webhook", json={})
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_handle_message_authorized(authorized_message):
    """Test handling authorized message."""
    with patch("claude_telegram.main.run_claude", new_callable=AsyncMock) as mock_run:
        await handle_message(authorized_message["message"])
        mock_run.assert_called_once_with("Hello Claude", 12345, continue_session=False)


@pytest.mark.asyncio
async def test_handle_message_unauthorized(unauthorized_message):
    """Test handling unauthorized message."""
    with patch("claude_telegram.main.run_claude", new_callable=AsyncMock) as mock_run:
        await handle_message(unauthorized_message["message"])
        mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_empty_text():
    """Test handling message with no text."""
    message = {
        "chat": {"id": 12345},
        "text": "",
    }
    with patch("claude_telegram.main.run_claude", new_callable=AsyncMock) as mock_run:
        await handle_message(message)
        mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_handle_command_start():
    """Test /start command."""
    with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
        await handle_command("/start", "12345")
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert "Commands" in call_args[0][0]


@pytest.mark.asyncio
async def test_handle_command_continue():
    """Test /c command."""
    with patch("claude_telegram.main.run_claude", new_callable=AsyncMock) as mock_run:
        await handle_command("/c fix the bug", "12345")
        mock_run.assert_called_once_with("fix the bug", "12345", continue_session=True)


@pytest.mark.asyncio
async def test_handle_command_continue_alias():
    """Test /continue command."""
    with patch("claude_telegram.main.run_claude", new_callable=AsyncMock) as mock_run:
        await handle_command("/continue do something", "12345")
        mock_run.assert_called_once_with("do something", "12345", continue_session=True)


@pytest.mark.asyncio
async def test_handle_command_continue_no_args():
    """Test /c command without arguments."""
    with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
        await handle_command("/c", "12345")
        mock_send.assert_called_once()
        assert "Usage:" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_command_compact():
    """Test /compact command."""
    mock_runner = MagicMock()
    mock_runner.is_running = False
    mock_runner.compact = AsyncMock(return_value="Compacted")
    mock_runner.short_name = "test"
    with patch("claude_telegram.main.get_runner", return_value=mock_runner):
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock):
            with patch("claude_telegram.main.send_response", new_callable=AsyncMock) as mock_chunked:
                await handle_command("/compact", "12345")
                mock_runner.compact.assert_called_once()
                mock_chunked.assert_called_once()


@pytest.mark.asyncio
async def test_handle_command_compact_while_busy():
    """Test /compact when Claude is running."""
    mock_runner = MagicMock()
    mock_runner.is_running = True
    with patch("claude_telegram.main.get_runner", return_value=mock_runner):
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            await handle_command("/compact", "12345")
            assert "busy" in mock_send.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_handle_command_cancel():
    """Test /cancel command."""
    mock_runner = MagicMock()
    mock_runner.cancel = AsyncMock(return_value=True)
    mock_runner.short_name = "test"
    with patch("claude_telegram.main.get_runner", return_value=mock_runner):
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            await handle_command("/cancel", "12345")
            mock_runner.cancel.assert_called_once()
            assert "Cancelled" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_command_cancel_nothing():
    """Test /cancel when nothing is running."""
    mock_runner = MagicMock()
    mock_runner.cancel = AsyncMock(return_value=False)
    with patch("claude_telegram.main.get_runner", return_value=mock_runner):
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            await handle_command("/cancel", "12345")
            assert "Nothing" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_command_status():
    """Test /status command."""
    mock_runner = MagicMock()
    mock_runner.is_running = True
    mock_runner.is_in_conversation = MagicMock(return_value=True)
    mock_runner.short_name = "test"
    with patch("claude_telegram.main.get_runner", return_value=mock_runner):
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            await handle_command("/status", "12345")
            assert "Running" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_command_unknown():
    """Test unknown command."""
    with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
        await handle_command("/invalid", "12345")
        assert "Unknown" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_command_dir_with_path():
    """Test /dir command with path."""
    mock_session = MagicMock()
    mock_session.is_running = False
    mock_session.is_in_conversation = MagicMock(return_value=False)
    mock_session.short_name = "myproject"
    with patch("claude_telegram.main.sessions") as mock_sessions:
        mock_sessions.switch_session = MagicMock(return_value=mock_session)
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            await handle_command("/dir /path/to/myproject", "12345")
            mock_sessions.switch_session.assert_called_once_with("/path/to/myproject")
            assert "Switched" in mock_send.call_args[0][0]
            assert "myproject" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_command_dir_no_args():
    """Test /dir command without arguments."""
    mock_runner = MagicMock()
    mock_runner.short_name = "current"
    with patch("claude_telegram.main.get_runner", return_value=mock_runner):
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            await handle_command("/dir", "12345")
            assert "Current" in mock_send.call_args[0][0]
            assert "current" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_command_dirs():
    """Test /dirs command."""
    mock_session1 = MagicMock()
    mock_session1.is_running = False
    mock_session1.short_name = "project1"
    mock_session2 = MagicMock()
    mock_session2.is_running = True
    mock_session2.short_name = "project2"
    with patch("claude_telegram.main.sessions") as mock_sessions:
        mock_sessions.list_sessions = MagicMock(return_value=[
            ("/path/to/project1", mock_session1),
            ("/path/to/project2", mock_session2),
        ])
        with patch("claude_telegram.main.get_runner", return_value=mock_session1):
            with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
                await handle_command("/dirs", "12345")
                message = mock_send.call_args[0][0]
                assert "Active Sessions" in message
                assert "project1" in message
                assert "project2" in message


@pytest.mark.asyncio
async def test_handle_command_dirs_empty():
    """Test /dirs command with no sessions."""
    with patch("claude_telegram.main.sessions") as mock_sessions:
        mock_sessions.list_sessions = MagicMock(return_value=[])
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            await handle_command("/dirs", "12345")
            assert "No active sessions" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_callback_dir_switch():
    """Test callback for directory switching."""
    from claude_telegram.main import handle_callback
    mock_session = MagicMock()
    mock_session.is_running = False
    mock_session.is_in_conversation = MagicMock(return_value=False)
    mock_session.short_name = "myproject"
    callback = {
        "id": "123",
        "data": "dir:/path/to/myproject",
        "message": {"chat": {"id": 12345}},
    }
    with patch("claude_telegram.main.sessions") as mock_sessions:
        mock_sessions.switch_session = MagicMock(return_value=mock_session)
        with patch("claude_telegram.main.telegram.answer_callback", new_callable=AsyncMock):
            with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
                await handle_callback(callback)
                mock_sessions.switch_session.assert_called_once_with("/path/to/myproject")
                assert "Switched" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_run_claude_when_busy():
    """Test run_claude when already running."""
    mock_runner = MagicMock()
    mock_runner.is_running = True
    mock_runner.short_name = "test"
    with patch("claude_telegram.main.get_runner", return_value=mock_runner):
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            await run_claude("Hello", "12345", continue_session=False)
            assert "busy" in mock_send.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_run_claude_success():
    """Test successful Claude run."""
    mock_runner = MagicMock()
    mock_runner.is_running = False
    mock_runner.run = AsyncMock(return_value="Claude response")
    mock_runner.short_name = "test"
    with patch("claude_telegram.main.get_runner", return_value=mock_runner):
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"result": {"message_id": 123}}
            with patch("claude_telegram.main.telegram.delete_message", new_callable=AsyncMock):
                with patch("claude_telegram.main.send_response", new_callable=AsyncMock) as mock_chunked:
                    await run_claude("Hello", "12345", continue_session=False)
                    mock_runner.run.assert_called_once()
                    mock_chunked.assert_called_once_with("Claude response", "12345", session_name="test")


@pytest.mark.asyncio
async def test_run_claude_error():
    """Test Claude run with error."""
    mock_runner = MagicMock()
    mock_runner.is_running = False
    mock_runner.run = AsyncMock(side_effect=Exception("Test error"))
    mock_runner.short_name = "test"
    with patch("claude_telegram.main.get_runner", return_value=mock_runner):
        with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"result": {"message_id": 123}}
            with patch("claude_telegram.main.telegram.delete_message", new_callable=AsyncMock):
                await run_claude("Hello", "12345", continue_session=False)
                # Should have sent error message
                calls = mock_send.call_args_list
                assert any("Error" in str(call) for call in calls)


@pytest.mark.asyncio
async def test_send_response_short():
    """Test send_response with short text."""
    with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
        await send_response("Short text", "12345")
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_response_empty():
    """Test send_response with empty text."""
    with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
        await send_response("", "12345")
        mock_send.assert_called_once()
        assert "no output" in mock_send.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_send_response_long():
    """Test send_response with long text requiring multiple messages."""
    # Text with newlines to test chunking (split_text breaks at newlines)
    long_text = ("x" * 3000 + "\n") * 3  # ~9000 chars with newlines
    with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock) as mock_send:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await send_response(long_text, "12345")
            assert mock_send.call_count >= 2  # Should split into multiple chunks


def test_notify_completed():
    """Test notification endpoint for completed."""
    with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock):
        response = client.post("/notify/completed")
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_notify_waiting():
    """Test notification endpoint for waiting."""
    with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock):
        response = client.post("/notify/waiting")
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_notify_custom():
    """Test notification endpoint for custom event."""
    with patch("claude_telegram.main.telegram.send_message", new_callable=AsyncMock):
        response = client.post("/notify/custom_event")
        assert response.status_code == 200
