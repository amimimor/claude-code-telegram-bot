"""Tests for Claude runner."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

from claude_telegram.claude import ClaudeRunner


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


@pytest.mark.asyncio
async def test_run_basic_message(runner, mock_process):
    """Test running Claude with a basic message."""
    mock_process.stdout = async_iter([b"Hello from Claude!\n"])

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await runner.run("Hello")

        assert "Hello from Claude!" in result
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert "--print" in call_args
        # Prompt is positional, not a flag
        assert "Hello" in call_args


@pytest.mark.asyncio
async def test_run_with_continue(runner, mock_process):
    """Test running Claude with --continue flag."""
    mock_process.stdout = async_iter([b"Continued response\n"])

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await runner.run("Continue this", continue_session=True)

        assert "Continued response" in result
        call_args = mock_exec.call_args[0]
        assert "--continue" in call_args


@pytest.mark.asyncio
async def test_run_without_continue(runner, mock_process):
    """Test running Claude without --continue flag."""
    mock_process.stdout = async_iter([b"New session\n"])

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await runner.run("New message", continue_session=False)

        call_args = mock_exec.call_args[0]
        assert "--continue" not in call_args


@pytest.mark.asyncio
async def test_run_with_callback(runner, mock_process):
    """Test running Claude with output callback."""
    mock_process.stdout = async_iter([b"Line 1\n", b"Line 2\n"])
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
    mock_process.stdout = async_iter([
        b"First line\n",
        b"Second line\n",
        b"Third line\n",
    ])

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await runner.run("Hello")

    assert "First line" in result
    assert "Second line" in result
    assert "Third line" in result


@pytest.mark.asyncio
async def test_compact(runner, mock_process):
    """Test running compaction."""
    mock_process.stdout = async_iter([b"Compaction complete\n"])

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await runner.compact()

        assert "Compaction complete" in result
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
    mock_process.stdout = async_iter([b"Done\n"])

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await runner.run("Hello")

    assert runner.current_process is None


@pytest.mark.asyncio
async def test_run_with_working_directory(mock_process):
    """Test running Claude with custom working directory."""
    mock_process.stdout = async_iter([b"Output\n"])

    runner = ClaudeRunner()
    runner.working_dir = "/custom/path"

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await runner.run("Hello")

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["cwd"].as_posix() == "/custom/path"


@pytest.mark.asyncio
async def test_run_handles_unicode(runner, mock_process):
    """Test handling of unicode output."""
    mock_process.stdout = async_iter([
        "Hello 世界! 🎉\n".encode("utf-8"),
    ])

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await runner.run("Unicode test")

    assert "世界" in result
    assert "🎉" in result
