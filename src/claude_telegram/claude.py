"""Claude Code runner - spawns and manages Claude processes."""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)

CONVERSATION_TIMEOUT = timedelta(minutes=10)


class ClaudeRunner:
    """Runs Claude Code for a specific working directory."""

    def __init__(self, working_dir: str | None = None):
        self.cli_path = settings.claude_cli_path
        self.working_dir = working_dir or settings.claude_working_dir
        self.current_process: asyncio.subprocess.Process | None = None
        self.last_interaction: datetime | None = None

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

        logger.info(f"Running: {' '.join(cmd)} in {self.working_dir or 'cwd'}")

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
        self.last_interaction = datetime.now()

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

    def is_in_conversation(self) -> bool:
        """Check if we're in an active conversation (should auto-continue)."""
        if self.last_interaction is None:
            return False
        return datetime.now() - self.last_interaction < CONVERSATION_TIMEOUT

    @property
    def short_name(self) -> str:
        """Get a short display name for this session."""
        if not self.working_dir:
            return "default"
        return Path(self.working_dir).name


class SessionManager:
    """Manages multiple Claude sessions across different directories."""

    def __init__(self):
        self.sessions: dict[str, ClaudeRunner] = {}
        self.current_dir: str | None = settings.claude_working_dir

    def get_session(self, working_dir: str | None = None) -> ClaudeRunner:
        """Get or create a session for the given directory."""
        dir_key = working_dir or self.current_dir or "default"

        if dir_key not in self.sessions:
            self.sessions[dir_key] = ClaudeRunner(working_dir=working_dir if working_dir != "default" else None)
            logger.info(f"Created new session for: {dir_key}")

        return self.sessions[dir_key]

    def get_current_session(self) -> ClaudeRunner:
        """Get the current active session."""
        return self.get_session(self.current_dir)

    def switch_session(self, working_dir: str) -> ClaudeRunner:
        """Switch to a different session/directory."""
        # Expand ~ and resolve path
        expanded = str(Path(working_dir).expanduser().resolve())
        self.current_dir = expanded
        return self.get_session(expanded)

    def list_sessions(self) -> list[tuple[str, ClaudeRunner]]:
        """List all active sessions."""
        return list(self.sessions.items())

    def any_running(self) -> bool:
        """Check if any session is currently running."""
        return any(s.is_running for s in self.sessions.values())

    def get_running_session(self) -> ClaudeRunner | None:
        """Get the currently running session, if any."""
        for session in self.sessions.values():
            if session.is_running:
                return session
        return None


# Global session manager
sessions = SessionManager()

# Backwards compatibility
runner = sessions.get_current_session()
