"""Load local configuration without displaying or logging secrets."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(ValueError):
    """An actionable configuration error, safe to display."""


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str = "deepseek-flash"
    timeout_seconds: float = 30.0
    base_url: str = "https://api.deepseek.com"
    budget_db: Path = Path(".state/llm-usage.sqlite3")
    request_limit: int = 200
    max_concurrent: int = 2
    max_input_chars: int = 120000

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


def load_settings(env_path: Path | None = None) -> Settings:
    # Read only the explicitly selected file or .env in the current project dir.
    # Environment variables take priority; do not search parent directories.
    load_dotenv(dotenv_path=env_path or Path.cwd() / ".env", override=False)
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key.lower() in {"your_api_key", "your-api-key", "your-api-key-here", "sk-..."}:
        key = ""
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash").strip()
    if not model:
        raise ConfigError("DEEPSEEK_MODEL 不能为空。")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
    # These are the two endpoints explicitly selected for this project so far.
    # Reject full completion paths, embedded credentials and unintended hosts.
    if base_url not in {"https://api.deepseek.com", "https://api.chatanywhere.tech/v1"}:
        raise ConfigError("DEEPSEEK_BASE_URL 请填写官网地址或 https://api.chatanywhere.tech/v1，勿附加 /chat/completions。")
    try:
        timeout = float(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "30"))
    except ValueError:
        raise ConfigError("DEEPSEEK_TIMEOUT_SECONDS 必须是5–30之间的数字。") from None
    if not 5 <= timeout <= 30:
        raise ConfigError("DEEPSEEK_TIMEOUT_SECONDS 必须在5–30之间。")
    try:
        limit = int(os.environ.get("SLEEPLENS_REQUEST_LIMIT", "200"))
        concurrent = int(os.environ.get("SLEEPLENS_MAX_CONCURRENT", "2"))
        chars = int(os.environ.get("SLEEPLENS_MAX_INPUT_CHARS", "120000"))
    except ValueError:
        raise ConfigError("服务额度、并发和输入长度必须为整数。") from None
    # Zero disables only the lifetime request cap; admission limits still apply.
    if not 0 <= limit <= 100000 or not 1 <= concurrent <= 20 or not 1000 <= chars <= 500000:
        raise ConfigError("服务额度、并发或输入长度配置超出范围。")
    root = (env_path.parent if env_path else Path.cwd()).resolve()
    db = Path(os.environ.get("SLEEPLENS_BUDGET_DB", ".state/llm-usage.sqlite3"))
    db = (root / db).resolve()
    if root not in db.parents:
        raise ConfigError("额度账本必须位于项目目录内。")
    return Settings(api_key=key, model=model, timeout_seconds=timeout, base_url=base_url,
                    budget_db=db, request_limit=limit, max_concurrent=concurrent, max_input_chars=chars)


@dataclass(frozen=True)
class ShareSettings:
    enabled: bool = False
    password: str = field(default="", repr=False)
    log_days: int = 7


def load_share_settings():
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    enabled = os.environ.get("SLEEPLENS_SHARE_MODE", "0").lower() in {"1", "true"}
    password = os.environ.get("SLEEPLENS_SHARE_PASSWORD", "")
    try:
        days = int(os.environ.get("SLEEPLENS_SHARE_LOG_DAYS", "7"))
    except ValueError:
        raise ConfigError("分享日志保留天数必须是整数。") from None
    if not 1 <= days <= 30 or (enabled and len(password) < 12):
        raise ConfigError("分享模式需要至少12字符访问口令，日志保留1–30天。")
    return ShareSettings(enabled, password, days)
