import os
import tomllib
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from mailbot.models import Account


def _integer(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом") from exc
    if value < minimum:
        raise ValueError(f"{name} должен быть не меньше {minimum}")
    return value


def _parse_time(value: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":"))
        return time(hour=hour, minute=minute)
    except (ValueError, TypeError) as exc:
        raise ValueError("DIGEST_TIME должен иметь формат ЧЧ:ММ") from exc


def _csv(name: str) -> tuple[str, ...]:
    return tuple(item.strip().casefold() for item in os.getenv(name, "").split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_token: str
    allowed_user_id: int
    telegram_proxy_url: str | None
    accounts_file: Path
    database_path: Path
    timezone: ZoneInfo
    poll_interval_seconds: int
    poll_concurrency: int
    first_sync_hours: int
    importance_threshold: int
    digest_time: time
    openai_api_key: str | None
    openai_model: str
    important_senders: tuple[str, ...]
    ignored_senders: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("Не задан TELEGRAM_BOT_TOKEN")

        timezone_name = os.getenv("TIMEZONE", "Europe/Moscow")
        try:
            timezone = ZoneInfo(timezone_name)
        except Exception as exc:
            raise ValueError(f"Неизвестный часовой пояс: {timezone_name}") from exc

        return cls(
            telegram_token=token,
            allowed_user_id=_integer("ALLOWED_TELEGRAM_USER_ID", 0),
            telegram_proxy_url=os.getenv("TELEGRAM_PROXY_URL") or None,
            accounts_file=Path(os.getenv("ACCOUNTS_FILE", "config/accounts.toml")),
            database_path=Path(os.getenv("DATABASE_PATH", "data/mailbot.sqlite3")),
            timezone=timezone,
            poll_interval_seconds=_integer("POLL_INTERVAL_SECONDS", 180, 30),
            poll_concurrency=_integer("POLL_CONCURRENCY", 3, 1),
            first_sync_hours=_integer("FIRST_SYNC_HOURS", 24, 1),
            importance_threshold=_integer("IMPORTANCE_THRESHOLD", 70, 1),
            digest_time=_parse_time(os.getenv("DIGEST_TIME", "21:00")),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            important_senders=_csv("IMPORTANT_SENDERS"),
            ignored_senders=_csv("IGNORED_SENDERS"),
        )


def load_accounts(path: Path) -> list[Account]:
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл аккаунтов: {path}")

    with path.open("rb") as source:
        rows = tomllib.load(source).get("accounts", [])

    accounts: list[Account] = []
    seen_ids: set[str] = set()
    for row in rows:
        account_id = str(row.get("id", "")).strip()
        email = str(row.get("email", "")).strip()
        provider = str(row.get("provider", "")).strip().casefold()
        password_env = str(row.get("password_env", "")).strip()
        folder = str(row.get("folder", "INBOX")).strip()

        if not account_id or account_id in seen_ids:
            raise ValueError(f"Некорректный или повторяющийся id аккаунта: {account_id!r}")
        if "@" not in email:
            raise ValueError(f"Некорректный адрес в аккаунте {account_id}")
        if provider not in {"gmail", "mailru"}:
            raise ValueError(f"Провайдер {provider!r} не поддерживается")
        password = os.getenv(password_env, "")
        if not password:
            raise ValueError(f"Для {account_id} не задана переменная {password_env}")

        seen_ids.add(account_id)
        accounts.append(Account(account_id, email, provider, password, folder))

    if not accounts:
        raise ValueError("В accounts.toml нет ни одного аккаунта")
    return accounts
