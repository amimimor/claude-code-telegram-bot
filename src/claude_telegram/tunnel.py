"""Cloudflare Tunnel integration for webhook mode."""

import asyncio
import logging
import re
import shutil
from typing import Callable

logger = logging.getLogger(__name__)


class CloudflareTunnel:
    """Manages a cloudflared quick tunnel."""

    def __init__(self, port: int = 8000):
        self.port = port
        self.process: asyncio.subprocess.Process | None = None
        self.url: str | None = None
        self._on_url_callback: Callable[[str], None] | None = None

    @staticmethod
    def is_available() -> bool:
        """Check if cloudflared is installed."""
        return shutil.which("cloudflared") is not None

    async def start(self, on_url: Callable[[str], None] | None = None) -> str | None:
        """
        Start the tunnel and return the public URL.

        Args:
            on_url: Optional callback when URL is discovered

        Returns:
            The public tunnel URL, or None if failed
        """
        if not self.is_available():
            logger.error("cloudflared not found. Install it: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
            return None

        self._on_url_callback = on_url

        try:
            # Start cloudflared tunnel
            self.process = await asyncio.create_subprocess_exec(
                "cloudflared", "tunnel", "--url", f"http://localhost:{self.port}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            # Read output to find the URL
            self.url = await self._wait_for_url(timeout=30)

            if self.url:
                logger.info(f"Tunnel started: {self.url}")
                if self._on_url_callback:
                    self._on_url_callback(self.url)
                return self.url
            else:
                logger.error("Failed to get tunnel URL")
                await self.stop()
                return None

        except Exception as e:
            logger.exception(f"Failed to start tunnel: {e}")
            return None

    async def _wait_for_url(self, timeout: int = 30) -> str | None:
        """Wait for cloudflared to output the tunnel URL."""
        if not self.process or not self.process.stdout:
            return None

        url_pattern = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')

        try:
            async with asyncio.timeout(timeout):
                async for line in self.process.stdout:
                    decoded = line.decode("utf-8", errors="replace")
                    logger.debug(f"cloudflared: {decoded.strip()}")

                    match = url_pattern.search(decoded)
                    if match:
                        return match.group(0)

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for tunnel URL after {timeout}s")

        return None

    async def stop(self):
        """Stop the tunnel."""
        if self.process:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
            self.process = None
            self.url = None
            logger.info("Tunnel stopped")

    @property
    def is_running(self) -> bool:
        """Check if tunnel is running."""
        return self.process is not None and self.process.returncode is None


# Global tunnel instance
tunnel = CloudflareTunnel()
