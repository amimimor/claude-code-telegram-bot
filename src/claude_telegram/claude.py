"""Claude Code runner - spawns and manages Claude processes."""

import asyncio
import logging
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)


class ClaudeRunner:
    """Runs Claude Code and captures output."""

    def __init__(self):
        self.cli_path = settings.claude_cli_path
        self.working_dir = settings.claude_working_dir
        self.current_process: asyncio.subprocess.Process | None = None

    async def run(
        self,
        message: str,
        *,
        continue_session: bool = False,
        on_output: callable = None,
    ) -> str:
        """
        Run Claude Code with a message.

        Args:
            message: The prompt to send to Claude
            continue_session: If True, use --continue flag
            on_output: Optional callback for streaming output

        Returns:
            Claude's response
        """
        cmd = [self.cli_path, "--print"]

        if continue_session:
            cmd.append("--continue")

        # Prompt is a positional argument, not a flag
        cmd.append(message)

        logger.info(f"Running: {' '.join(cmd)}")

        cwd = Path(self.working_dir) if self.working_dir else None

        self.current_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )

        output_lines = []

        async for line in self.current_process.stdout:
            decoded = line.decode("utf-8", errors="replace")
            output_lines.append(decoded)
            if on_output:
                await on_output(decoded)

        await self.current_process.wait()
        self.current_process = None

        return "".join(output_lines)

    async def compact(self) -> str:
        """Run compaction on the current session."""
        return await self.run("/compact", continue_session=True)

    async def cancel(self) -> bool:
        """Cancel the currently running Claude process."""
        if self.current_process:
            self.current_process.terminate()
            await self.current_process.wait()
            self.current_process = None
            return True
        return False

    @property
    def is_running(self) -> bool:
        """Check if Claude is currently running."""
        return self.current_process is not None


runner = ClaudeRunner()
