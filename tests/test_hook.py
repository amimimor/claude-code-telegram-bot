"""Tests for hook script."""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os


def test_hook_notify_completed():
    """Test hook notification for completed event."""
    with patch("httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        # Import and test
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from hook import notify

        notify("completed")

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "notify/completed" in call_url


def test_hook_notify_waiting():
    """Test hook notification for waiting event."""
    with patch("httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        from hook import notify

        notify("waiting")

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "notify/waiting" in call_url


def test_hook_notify_error():
    """Test hook notification error handling."""
    with patch("httpx.post") as mock_post:
        mock_post.side_effect = Exception("Connection error")

        from hook import notify

        with pytest.raises(SystemExit) as exc_info:
            notify("completed")

        assert exc_info.value.code == 1


def test_hook_custom_server_url():
    """Test hook with custom server URL."""
    with patch.dict(os.environ, {"HOOK_SERVER_URL": "http://custom:9000"}):
        # Need to reimport to pick up new env
        import importlib
        import hook
        importlib.reload(hook)

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            hook.notify("completed")

            call_url = mock_post.call_args[0][0]
            assert "custom:9000" in call_url
