from datetime import datetime
from html import escape

from mailbot.models import Classification, MailMessage, StoredMessage


CATEGORY_LABELS = {
    "code": "🔐 Код",
    "security": "🚨 Безопасность",
    "work": "💼 Работа",
    "study": "🎓 Учёба",
    "personal": "👤 Личное",
    "finance": "💳 Финансы",
    "newsletter": "📰 Рассылка",
    "other": "✉️ Другое",
}


def notification(message: MailMessage, result: Classification, local_time: datetime) -> str:
    label = CATEGORY_LABELS.get(result.category, "✉️ Письмо")
    return (
        f"{label} · <b>{result.importance}/100</b>\n"
        f"<b>{escape(message.subject)}</b>\n"
        f"От: {escape(message.sender)}\n"
        f"Ящик: <code>{escape(message.account_email)}</code>\n"
        f"Время: {local_time:%d.%m %H:%M}\n\n"
        f"{escape(result.summary)}"
    )


def digest(messages: list[StoredMessage], title: str, timezone) -> list[str]:
    if not messages:
        return [f"<b>{escape(title)}</b>\n\nПисем за этот период нет."]

    chunks: list[str] = []
    current = f"<b>{escape(title)}</b>\nВсего писем: {len(messages)}\n\n"
    for index, item in enumerate(messages, 1):
        received = item.received_at.astimezone(timezone)
        label = CATEGORY_LABELS.get(item.category, "✉️ Другое")
        block = (
            f"<b>{index}. {escape(item.subject)}</b>\n"
            f"{label} · {item.importance}/100 · {received:%d.%m %H:%M}\n"
            f"{escape(item.account_email)} · {escape(item.sender)}\n"
            f"{escape(item.summary)}\n\n"
        )
        if len(current) + len(block) > 3900:
            chunks.append(current.rstrip())
            current = block
        else:
            current += block
    chunks.append(current.rstrip())
    return chunks

