"""Configuration settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str  # Allowed chat ID for security

    # Claude
    claude_cli_path: str = "claude"
    claude_working_dir: str | None = None

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    webhook_path: str = "/webhook"
    webhook_url: str | None = None  # Manual webhook URL (for "webhook" mode)

    # Mode: "tunnel" (default), "polling", or "webhook"
    # - tunnel: Auto-creates Cloudflare tunnel (recommended)
    # - polling: No public URL needed, polls Telegram API
    # - webhook: Use manual webhook_url
    mode: str = "tunnel"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
