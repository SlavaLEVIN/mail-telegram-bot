from datetime import datetime
from html import escape

from mailbot.models import Classification, MailMessage, StoredMessage


CATEGORY_LABELS = {
    "code": "🔐 Код",
    "security": "🚨 Безопасность",
    "work": "💼 Работа",
    "study": "🎓 Учёба",
    "deadline": "⏳ Дедлайн",
    "event": "📅 Встреча",
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


def message_card(message: StoredMessage, timezone) -> str:
    received = message.received_at.astimezone(timezone)
    label = CATEGORY_LABELS.get(message.category, "✉️ Другое")
    summary = message.summary.strip()
    if summary.casefold() == message.subject.strip().casefold():
        summary = ""
    text = (
        f"{label} · <b>{message.importance}/100</b>\n"
        f"<b>{escape(message.subject)}</b>\n\n"
        f"От: {escape(message.sender)}\n"
        f"Получено: {received:%d.%m.%Y %H:%M}\n"
    )
    if summary:
        text += f"\n{escape(summary)}"
    return text


def digest(messages: list[StoredMessage], title: str, timezone) -> list[str]:
    if not messages:
        return [f"<b>{escape(title)}</b>\n\nПисем за этот период нет."]

    chunks: list[str] = []
    current = f"<b>{escape(title)}</b>\nВсего: {len(messages)} · по убыванию важности\n\n"
    for index, item in enumerate(messages, 1):
        received = item.received_at.astimezone(timezone)
        label = CATEGORY_LABELS.get(item.category, "✉️ Другое")
        summary = item.summary.strip()
        if summary.casefold() == item.subject.strip().casefold():
            summary = "Краткое описание пока совпадает с темой."
        if len(summary) > 500:
            summary = summary[:497].rstrip() + "…"
        block = (
            f"<b>{index}. {escape(item.subject)}</b>\n"
            f"{label} · {item.importance}/100 · {received:%d.%m %H:%M}\n"
            f"{escape(summary)}\n\n"
        )
        if len(current) + len(block) > 3900:
            chunks.append(current.rstrip())
            current = block
        else:
            current += block
    chunks.append(current.rstrip())
    return chunks
