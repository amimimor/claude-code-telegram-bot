"""Tests for Claude runner."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

from claude_telegram.claude import ClaudeRunner, ClaudeResult, PermissionDenial


@pytest.fixture
def runner():
    """Create a fresh runner for each test."""
    return ClaudeRunner()


@pytest.fixture
def mock_process():
    """Create a mock subprocess."""
    process = AsyncMock()
    process.wait = AsyncMock(return_value=0)
    process.terminate = MagicMock()
    return process


async def async_iter(items):
    """Helper to create async iterator."""
    for item in items:
        yield item


def make_stream_json(result_text: str, permission_denials: list = None):
    """Create mock stream-json output."""
    events = [
        # Init event
        json.dumps({"type": "system", "subtype": "init", "session_id": "test-session"}).encode() + b"\n",
        # Assistant response
        json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": result_text}]}
        }).encode() + b"\n",
        # Result event
        json.dumps({
            "type": "result",
            "result": result_text,
            "session_id": "test-session",
            "permission_denials": permission_denials or []
        }).encode() + b"\n",
    ]
    return events


@pytest.mark.asyncio
async def test_run_basic_message(runner, mock_process):
    """Test running Claude with a basic message."""
    mock_process.stdout = async_iter(make_stream_json("Hello from Claude!"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await runner.run("Hello")

        assert isinstance(result, ClaudeResult)
        assert "Hello from Claude!" in result.text
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert "--print" in call_args
        assert "--output-format" in call_args
        assert "stream-json" in call_args


@pytest.mark.asyncio
async def test_run_with_continue(runner, mock_process):
    """Test running Claude with --continue flag."""
    mock_process.stdout = async_iter(make_stream_json("Continued response"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await runner.run("Continue this", continue_session=True)

        assert "Continued response" in result.text
        call_args = mock_exec.call_args[0]
        assert "--continue" in call_args


@pytest.mark.asyncio
async def test_run_without_continue(runner, mock_process):
    """Test running Claude without --continue flag."""
    mock_process.stdout = async_iter(make_stream_json("New session"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await runner.run("New message", continue_session=False)

        call_args = mock_exec.call_args[0]
        assert "--continue" not in call_args


@pytest.mark.asyncio
async def test_run_with_callback(runner, mock_process):
    """Test running Claude with output callback."""
    # Create events with multiple text chunks
    events = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "test"}).encode() + b"\n",
        json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Line 1"}]}
        }).encode() + b"\n",
        json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Line 2"}]}
        }).encode() + b"\n",
        json.dumps({
            "type": "result",
            "result": "Line 1\nLine 2",
            "session_id": "test",
            "permission_denials": []
        }).encode() + b"\n",
    ]
    mock_process.stdout = async_iter(events)
    collected = []

    async def callback(line):
        collected.append(line)

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await runner.run("Hello", on_output=callback)

    assert len(collected) == 2
    assert "Line 1" in collected[0]
    assert "Line 2" in collected[1]


@pytest.mark.asyncio
async def test_run_multiline_output(runner, mock_process):
    """Test running Claude with multiline output."""
    mock_process.stdout = async_iter(make_stream_json("First line\nSecond line\nThird line"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await runner.run("Hello")

    assert "First line" in result.text
    assert "Second line" in result.text
    assert "Third line" in result.text


@pytest.mark.asyncio
async def test_compact(runner, mock_process):
    """Test running compaction."""
    mock_process.stdout = async_iter(make_stream_json("Compaction complete"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await runner.compact()

        assert "Compaction complete" in result.text
        call_args = mock_exec.call_args[0]
        assert "--continue" in call_args
        assert "/compact" in call_args


@pytest.mark.asyncio
async def test_cancel_running_process(runner, mock_process):
    """Test cancelling a running process."""
    runner.current_process = mock_process

    result = await runner.cancel()

    assert result is True
    mock_process.terminate.assert_called_once()
    assert runner.current_process is None


@pytest.mark.asyncio
async def test_cancel_no_process(runner):
    """Test cancelling when nothing is running."""
    result = await runner.cancel()
    assert result is False


def test_is_running_true(runner, mock_process):
    """Test is_running when process exists."""
    runner.current_process = mock_process
    assert runner.is_running is True


def test_is_running_false(runner):
    """Test is_running when no process."""
    assert runner.is_running is False


@pytest.mark.asyncio
async def test_run_clears_process_after_completion(runner, mock_process):
    """Test that process reference is cleared after completion."""
    mock_process.stdout = async_iter(make_stream_json("Done"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await runner.run("Hello")

    assert runner.current_process is None


@pytest.mark.asyncio
async def test_run_with_working_directory(mock_process):
    """Test running Claude with custom working directory."""
    mock_process.stdout = async_iter(make_stream_json("Output"))

    runner = ClaudeRunner()
    runner.working_dir = "/custom/path"

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await runner.run("Hello")

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["cwd"].as_posix() == "/custom/path"


@pytest.mark.asyncio
async def test_run_handles_unicode(runner, mock_process):
    """Test handling of unicode output."""
    mock_process.stdout = async_iter(make_stream_json("Hello 世界! 🎉"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await runner.run("Unicode test")

    assert "世界" in result.text
    assert "🎉" in result.text


@pytest.mark.asyncio
async def test_run_with_permission_denials(runner, mock_process):
    """Test running Claude with permission denials."""
    denials = [
        {"tool_name": "Write", "tool_input": {"file_path": "/tmp/test.txt"}, "tool_use_id": "123"}
    ]
    mock_process.stdout = async_iter(make_stream_json("Permission denied", denials))

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await runner.run("Write to /tmp/test.txt")

    assert len(result.permission_denials) == 1
    assert result.permission_denials[0].tool_name == "Write"
    assert result.permission_denials[0].tool_input["file_path"] == "/tmp/test.txt"


@pytest.mark.asyncio
async def test_run_with_allowed_tools(runner, mock_process):
    """Test running Claude with allowed tools."""
    mock_process.stdout = async_iter(make_stream_json("Done"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await runner.run("Hello", allowed_tools=["Write:/tmp/*", "Bash:echo *"])

        call_args = mock_exec.call_args[0]
        assert "--allowedTools" in call_args
        idx = call_args.index("--allowedTools")
        assert "Write:/tmp/*,Bash:echo *" in call_args[idx + 1]
