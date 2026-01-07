"""Claude Code runner - spawns and manages Claude processes."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .config import settings


@dataclass
class PermissionDenial:
    """A permission that was denied during Claude execution."""
    tool_name: str
    tool_input: dict
    tool_use_id: str = ""


@dataclass
class ClaudeResult:
    """Result from running Claude, including any permission denials."""
    text: str
    permission_denials: list[PermissionDenial] = field(default_factory=list)
    session_id: str | None = None

logger = logging.getLogger(__name__)

CONVERSATION_TIMEOUT = timedelta(minutes=10)
CLAUDE_DIR = Path.home() / ".claude"


def get_project_dir(working_dir: str) -> Path | None:
    """Get the Claude project directory for a working directory."""
    # Claude stores projects in ~/.claude/projects/<path-with-dashes>/
    # e.g., /Users/foo/bar -> -Users-foo-bar
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.exists():
        return None

    # Convert path to Claude's format: /Users/foo/bar -> -Users-foo-bar
    abs_path = str(Path(working_dir).resolve())
    claude_dir_name = abs_path.replace("/", "-")  # Keep leading dash

    # Check for exact path match
    project_path = projects_dir / claude_dir_name
    if project_path.exists() and project_path.is_dir():
        return project_path

    # Fallback: look for any project dir that might match
    dir_name = working_dir.split("/")[-1]
    for project_path in projects_dir.iterdir():
        if project_path.is_dir() and project_path.name.endswith(f"-{dir_name}"):
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
        self.context_shown: bool = False  # Track if we've shown context for resumed session

    def get_session_context(self) -> str | None:
        """Get the last few user messages from a stored session."""
        if not self.working_dir:
            return None

        project_dir = get_project_dir(self.working_dir)
        if not project_dir:
            return None

        # Find most recent session file
        sessions = [
            f for f in project_dir.glob("*.jsonl")
            if not f.name.startswith("agent-") and f.stat().st_size > 0
        ]
        if not sessions:
            return None

        latest = max(sessions, key=lambda f: f.stat().st_mtime)
        self.session_id = latest.stem

        # Read and parse user messages
        messages = []
        try:
            with open(latest, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get("type") == "user":
                            content = data.get("message", {}).get("content", [])
                            # Content can be a string or a list
                            if isinstance(content, str):
                                text = content.strip()
                                if text and len(text) > 10 and not text.startswith("[Request"):
                                    messages.append(text[:120])
                            elif isinstance(content, list):
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "text":
                                        text = c.get("text", "").strip()
                                        if text and len(text) > 10 and not text.startswith("[Request"):
                                            messages.append(text[:120])
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Failed to read session file: {e}")
            return None

        if not messages:
            return None

        self.context_shown = True
        # Return last 5 messages as bullet points
        return "\n".join(f"• {m}" for m in messages[-5:])

    async def run(
        self,
        message: str,
        *,
        continue_session: bool = False,
        on_output: callable = None,
        allowed_tools: list[str] | None = None,
    ) -> ClaudeResult:
        """
        Run Claude Code with a message.

        Args:
            message: The prompt to send to Claude
            continue_session: If True, resume the session
            on_output: Optional callback for streaming output
            allowed_tools: Optional list of tools to allow (e.g., ["Write", "Bash(echo:*)"])

        Returns:
            ClaudeResult with response text and any permission denials
        """
        cmd = [self.cli_path, "--print", "--output-format", "stream-json", "--verbose"]

        # Add allowed tools if specified
        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])

        # Always try to resume an existing session for this directory
        if self.session_id:
            # We already have a session ID from previous run
            cmd.extend(["--resume", self.session_id])
        elif self.working_dir:
            # Try to find existing session for this directory
            session_id = find_latest_session(self.working_dir)
            if session_id:
                cmd.extend(["--resume", session_id])
                self.session_id = session_id
                logger.info(f"Resuming stored session {session_id} for {self.short_name}")
            elif continue_session:
                # Fallback to --continue if explicitly requested
                cmd.append("--continue")
        elif continue_session:
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

        # Parse stream-json output
        result_text = ""
        permission_denials = []
        result_session_id = None

        async for line in self.current_process.stdout:
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                continue

            try:
                event = json.loads(decoded)
                event_type = event.get("type")

                # Extract result text from the final result event
                if event_type == "result":
                    result_text = event.get("result", "")
                    result_session_id = event.get("session_id")
                    # Parse permission denials
                    for denial in event.get("permission_denials", []):
                        permission_denials.append(PermissionDenial(
                            tool_name=denial.get("tool_name", ""),
                            tool_input=denial.get("tool_input", {}),
                            tool_use_id=denial.get("tool_use_id", ""),
                        ))

                # Stream assistant text content for real-time output
                if event_type == "assistant" and on_output:
                    content = event.get("message", {}).get("content", [])
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            await on_output(c.get("text", ""))

            except json.JSONDecodeError:
                # Not JSON, might be stderr or other output
                logger.debug(f"Non-JSON output: {decoded}")
                continue

        await self.current_process.wait()
        self.current_process = None
        self.last_interaction = datetime.now()

        # Update session ID after run
        if result_session_id:
            self.session_id = result_session_id
        elif self.working_dir:
            new_session_id = find_latest_session(self.working_dir)
            if new_session_id:
                self.session_id = new_session_id

        if self.session_id:
            logger.info(f"Session ID for {self.short_name}: {self.session_id}")

        return ClaudeResult(
            text=result_text,
            permission_denials=permission_denials,
            session_id=self.session_id,
        )

    async def compact(self) -> ClaudeResult:
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

    def remove_session(self, working_dir: str) -> bool:
        """Remove a session from the manager. Returns True if removed."""
        # Normalize path like switch_session does
        if not working_dir.startswith("/") and not working_dir.startswith("~"):
            working_dir = f"~/{working_dir}"
        resolved = str(Path(working_dir).expanduser().resolve())

        if resolved in self.sessions:
            session = self.sessions[resolved]
            # Don't remove if running
            if session.is_running:
                return False
            del self.sessions[resolved]
            # If we removed the current session, switch to another or default
            if self.current_dir == resolved:
                if self.sessions:
                    self.current_dir = next(iter(self.sessions.keys()))
                else:
                    self.current_dir = str(Path.home())
            return True
        return False

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
