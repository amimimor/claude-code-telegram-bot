"""Claude Code runner - spawns and manages Claude processes."""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)

CONVERSATION_TIMEOUT = timedelta(minutes=10)
CLAUDE_DIR = Path.home() / ".claude"


def get_project_dir(working_dir: str) -> Path | None:
    """Get the Claude project directory for a working directory."""
    # Claude stores projects in ~/.claude/projects/<path-hash>/
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.exists():
        return None

    # Try to find matching project directory
    # Claude uses the absolute path as the directory name
    abs_path = str(Path(working_dir).resolve())

    # Check for exact path match first
    for project_path in projects_dir.iterdir():
        if project_path.is_dir() and project_path.name == abs_path.replace("/", "-")[1:]:
            return project_path

    # Fallback: look for any project dir that might match
    for project_path in projects_dir.iterdir():
        if project_path.is_dir():
            # Check if this looks like our project
            if working_dir.split("/")[-1] in project_path.name:
                return project_path

    return None


def find_latest_session(working_dir: str) -> str | None:
    """Find the most recent session ID for a working directory."""
    project_dir = get_project_dir(working_dir)
    if not project_dir:
        return None

    # Find most recent .jsonl file (excluding agent-* files)
    sessions = [
        f for f in project_dir.glob("*.jsonl")
        if not f.name.startswith("agent-")
    ]

    if not sessions:
        return None

    # Get most recently modified
    latest = max(sessions, key=lambda f: f.stat().st_mtime)
    # Return session ID (filename without .jsonl)
    return latest.stem


class ClaudeRunner:
    """Runs Claude Code for a specific working directory."""

    def __init__(self, working_dir: str | None = None):
        self.cli_path = settings.claude_cli_path
        self.working_dir = working_dir or settings.claude_working_dir
        self.current_process: asyncio.subprocess.Process | None = None
        self.last_interaction: datetime | None = None
        self.session_id: str | None = None  # Track session ID for --resume

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
            continue_session: If True, resume the session
            on_output: Optional callback for streaming output

        Returns:
            Claude's response
        """
        cmd = [self.cli_path, "--print"]

        if continue_session:
            # Try to resume specific session, fall back to --continue
            if self.session_id:
                cmd.extend(["--resume", self.session_id])
            else:
                # Try to find existing session for this directory
                session_id = find_latest_session(self.working_dir)
                if session_id:
                    cmd.extend(["--resume", session_id])
                    self.session_id = session_id
                else:
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

        # Update session ID after run (new session may have been created)
        if self.working_dir:
            new_session_id = find_latest_session(self.working_dir)
            if new_session_id:
                self.session_id = new_session_id
                logger.info(f"Session ID for {self.short_name}: {self.session_id}")

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
        # Default to configured dir, or home directory if not set
        default_dir = settings.claude_working_dir
        if not default_dir:
            default_dir = str(Path.home())
        self.current_dir: str = default_dir

    def get_session(self, working_dir: str | None = None) -> ClaudeRunner:
        """Get or create a session for the given directory."""
        dir_key = working_dir or self.current_dir

        if dir_key not in self.sessions:
            self.sessions[dir_key] = ClaudeRunner(working_dir=dir_key)
            logger.info(f"Created new session for: {dir_key}")

        return self.sessions[dir_key]

    def get_current_session(self) -> ClaudeRunner:
        """Get the current active session."""
        return self.get_session(self.current_dir)

    def switch_session(self, working_dir: str) -> ClaudeRunner:
        """Switch to a different session/directory."""
        # Treat paths without / or ~ prefix as relative to home
        if not working_dir.startswith("/") and not working_dir.startswith("~"):
            working_dir = f"~/{working_dir}"
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
