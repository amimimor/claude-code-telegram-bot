"""Convert Markdown to Telegram HTML."""

import re
import html


def markdown_to_telegram_html(text: str) -> str:
    """
    Convert markdown to Telegram-supported HTML.

    Telegram supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a href="">
    """
    # Escape HTML entities first (but we'll unescape our tags later)
    text = html.escape(text)

    # Code blocks (``` ... ```) - must be done before inline code
    text = re.sub(
        r'```(\w*)\n(.*?)```',
        lambda m: f'<pre>{m.group(2)}</pre>',
        text,
        flags=re.DOTALL
    )

    # Inline code (` ... `)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Bold (**text** or __text__)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # Italic (*text* or _text_) - be careful not to match inside words
    text = re.sub(r'(?<!\w)\*([^*]+)\*(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'<i>\1</i>', text)

    # Strikethrough (~~text~~)
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # Links [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Headers (# text) - make them bold
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)

    return text


def safe_telegram_text(text: str) -> str:
    """
    Prepare text for Telegram, escaping special characters if not using parse_mode.
    """
    return html.escape(text)
