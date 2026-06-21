from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - installed through pyproject in normal use
    load_dotenv = None


@dataclass(frozen=True)
class Settings:
    email_address: str
    email_username: str
    email_password: str
    imap_host: str
    imap_port: int
    imap_ssl: bool
    search_default_days: int
    thread_lookback_days: int
    inbox_mailbox: str
    sent_mailbox: str
    log_level: str


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings(env_file: str | None = None) -> Settings:
    """加载本地配置；账号和授权码只从环境变量或 .env 读取。"""
    if load_dotenv:
        load_dotenv(dotenv_path=env_file or Path.cwd() / ".env", override=False)

    missing = [
        name
        for name in ["NETEASE_EMAIL_USERNAME", "NETEASE_EMAIL_PASSWORD"]
        if not os.getenv(name)
    ]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"缺少邮箱配置：{names}。请创建 .env 或设置环境变量。")

    username = os.environ["NETEASE_EMAIL_USERNAME"]
    return Settings(
        email_address=os.getenv("NETEASE_EMAIL_ADDRESS", username),
        email_username=username,
        email_password=os.environ["NETEASE_EMAIL_PASSWORD"],
        imap_host=os.getenv("NETEASE_IMAP_HOST", "imap.qiye.163.com"),
        imap_port=int(os.getenv("NETEASE_IMAP_PORT", "993")),
        imap_ssl=_as_bool(os.getenv("NETEASE_IMAP_SSL", "true")),
        search_default_days=int(os.getenv("EMAIL_SEARCH_DEFAULT_DAYS", "30")),
        thread_lookback_days=int(os.getenv("EMAIL_THREAD_LOOKBACK_DAYS", "90")),
        inbox_mailbox=os.getenv("NETEASE_INBOX_MAILBOX", "INBOX"),
        sent_mailbox=os.getenv("NETEASE_SENT_MAILBOX", "Sent"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
