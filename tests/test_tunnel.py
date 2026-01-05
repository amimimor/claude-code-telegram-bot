"""Tests for Cloudflare Tunnel integration."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

# Must patch before importing
with patch.dict("os.environ", {
    "TELEGRAM_BOT_TOKEN": "test_token",
    "TELEGRAM_CHAT_ID": "12345",
}):
    from claude_telegram.tunnel import CloudflareTunnel, tunnel


class TestCloudflareAvailability:
    """Test cloudflared availability checking."""

    def test_is_available_when_installed(self):
        """Test detection when cloudflared is installed."""
        with patch("shutil.which", return_value="/usr/local/bin/cloudflared"):
            assert CloudflareTunnel.is_available() is True

    def test_is_available_when_not_installed(self):
        """Test detection when cloudflared is not installed."""
        with patch("shutil.which", return_value=None):
            assert CloudflareTunnel.is_available() is False


class TestCloudfareTunnelStart:
    """Test tunnel start functionality."""

    @pytest.mark.asyncio
    async def test_start_returns_none_when_not_available(self):
        """Test start returns None if cloudflared not installed."""
        tun = CloudflareTunnel(port=8000)
        with patch.object(CloudflareTunnel, "is_available", return_value=False):
            result = await tun.start()
            assert result is None

    @pytest.mark.asyncio
    async def test_start_creates_subprocess(self):
        """Test start creates cloudflared subprocess."""
        tun = CloudflareTunnel(port=8000)

        mock_process = MagicMock()
        mock_process.stdout = AsyncMock()
        mock_process.returncode = None

        with patch.object(CloudflareTunnel, "is_available", return_value=True):
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = mock_process
                with patch.object(tun, "_wait_for_url", new_callable=AsyncMock) as mock_wait:
                    mock_wait.return_value = "https://test-abc.trycloudflare.com"

                    result = await tun.start()

                    assert result == "https://test-abc.trycloudflare.com"
                    mock_exec.assert_called_once()
                    args = mock_exec.call_args[0]
                    assert "cloudflared" in args
                    assert "tunnel" in args
                    assert "--url" in args
                    assert "http://localhost:8000" in args

    @pytest.mark.asyncio
    async def test_start_with_callback(self):
        """Test start calls callback with URL."""
        tun = CloudflareTunnel(port=8000)
        callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = AsyncMock()
        mock_process.returncode = None

        with patch.object(CloudflareTunnel, "is_available", return_value=True):
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = mock_process
                with patch.object(tun, "_wait_for_url", new_callable=AsyncMock) as mock_wait:
                    mock_wait.return_value = "https://test-xyz.trycloudflare.com"

                    await tun.start(on_url=callback)

                    callback.assert_called_once_with("https://test-xyz.trycloudflare.com")

    @pytest.mark.asyncio
    async def test_start_stops_on_url_failure(self):
        """Test start stops tunnel if URL not obtained."""
        tun = CloudflareTunnel(port=8000)

        mock_process = MagicMock()
        mock_process.stdout = AsyncMock()
        mock_process.returncode = None
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock()

        with patch.object(CloudflareTunnel, "is_available", return_value=True):
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = mock_process
                with patch.object(tun, "_wait_for_url", new_callable=AsyncMock) as mock_wait:
                    mock_wait.return_value = None  # URL not found

                    result = await tun.start()

                    assert result is None
                    mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_handles_exception(self):
        """Test start handles exceptions gracefully."""
        tun = CloudflareTunnel(port=8000)

        with patch.object(CloudflareTunnel, "is_available", return_value=True):
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
                mock_exec.side_effect = Exception("Failed to start")

                result = await tun.start()

                assert result is None


class TestCloudfareTunnelWaitForUrl:
    """Test URL detection from cloudflared output."""

    @pytest.mark.asyncio
    async def test_wait_for_url_finds_url(self):
        """Test URL extraction from cloudflared output."""
        tun = CloudflareTunnel(port=8000)

        # Mock stdout with async iterator
        async def mock_stdout():
            lines = [
                b"2024-01-01 INFO Starting tunnel\n",
                b"2024-01-01 INFO Registered tunnel connection\n",
                b"2024-01-01 INFO https://happy-dog-abc123.trycloudflare.com\n",
            ]
            for line in lines:
                yield line

        mock_process = MagicMock()
        mock_process.stdout = mock_stdout()
        tun.process = mock_process

        result = await tun._wait_for_url(timeout=5)

        assert result == "https://happy-dog-abc123.trycloudflare.com"

    @pytest.mark.asyncio
    async def test_wait_for_url_returns_none_on_no_process(self):
        """Test returns None if no process."""
        tun = CloudflareTunnel(port=8000)
        tun.process = None

        result = await tun._wait_for_url(timeout=1)

        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_url_returns_none_on_no_stdout(self):
        """Test returns None if process has no stdout."""
        tun = CloudflareTunnel(port=8000)
        mock_process = MagicMock()
        mock_process.stdout = None
        tun.process = mock_process

        result = await tun._wait_for_url(timeout=1)

        assert result is None


class TestCloudfareTunnelStop:
    """Test tunnel stop functionality."""

    @pytest.mark.asyncio
    async def test_stop_terminates_process(self):
        """Test stop terminates the process."""
        tun = CloudflareTunnel(port=8000)

        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock()
        tun.process = mock_process
        tun.url = "https://test.trycloudflare.com"

        await tun.stop()

        mock_process.terminate.assert_called_once()
        assert tun.process is None
        assert tun.url is None

    @pytest.mark.asyncio
    async def test_stop_kills_on_timeout(self):
        """Test stop kills process if terminate times out."""
        tun = CloudflareTunnel(port=8000)

        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        tun.process = mock_process

        await tun.stop()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_does_nothing_if_no_process(self):
        """Test stop does nothing if no process running."""
        tun = CloudflareTunnel(port=8000)
        tun.process = None

        # Should not raise
        await tun.stop()


class TestCloudfareTunnelIsRunning:
    """Test is_running property."""

    def test_is_running_true(self):
        """Test is_running returns True when process is active."""
        tun = CloudflareTunnel(port=8000)
        mock_process = MagicMock()
        mock_process.returncode = None
        tun.process = mock_process

        assert tun.is_running is True

    def test_is_running_false_no_process(self):
        """Test is_running returns False when no process."""
        tun = CloudflareTunnel(port=8000)
        tun.process = None

        assert tun.is_running is False

    def test_is_running_false_process_exited(self):
        """Test is_running returns False when process exited."""
        tun = CloudflareTunnel(port=8000)
        mock_process = MagicMock()
        mock_process.returncode = 0
        tun.process = mock_process

        assert tun.is_running is False


class TestGlobalTunnelInstance:
    """Test global tunnel instance."""

    def test_global_tunnel_exists(self):
        """Test global tunnel instance is created."""
        assert tunnel is not None
        assert isinstance(tunnel, CloudflareTunnel)
