from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from mailbot.config import Settings
from mailbot.database import Database
from mailbot.models import Account
from mailbot.presentation import digest


def digest_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📬 Письма за 24 часа", callback_data="digest:24")],
            [
                InlineKeyboardButton(text="6 часов", callback_data="digest:6"),
                InlineKeyboardButton(text="7 дней", callback_data="digest:168"),
            ],
        ]
    )


class BotHandlers:
    def __init__(self, settings: Settings, database: Database, accounts: list[Account]):
        self.settings = settings
        self.database = database
        self.accounts = accounts
        self.router = Router()
        self.router.message.register(self.whoami, Command("whoami"))
        self.router.message.register(self.start, Command("start", "help"))
        self.router.message.register(self.digest_command, Command("digest"))
        self.router.message.register(self.status, Command("status"))
        self.router.message.register(self.accounts_command, Command("accounts"))
        self.router.callback_query.register(self.digest_callback, F.data.startswith("digest:"))

    def authorized(self, user_id: int | None) -> bool:
        return self.settings.allowed_user_id > 0 and user_id == self.settings.allowed_user_id

    async def whoami(self, message: Message) -> None:
        if message.from_user:
            await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")

    async def start(self, message: Message) -> None:
        if not self.authorized(message.from_user.id if message.from_user else None):
            await message.answer("Доступ закрыт. Используйте /whoami и укажите ID в настройках бота.")
            return
        await message.answer(
            "Бот следит за почтой и присылает важные письма.\n\n"
            "/digest — сводка за сутки\n"
            "/status — состояние синхронизации\n"
            "/accounts — подключённые ящики",
            reply_markup=digest_keyboard(),
        )

    async def digest_command(self, message: Message) -> None:
        if not self.authorized(message.from_user.id if message.from_user else None):
            return
        await self.send_digest(message.bot, message.chat.id, 24)

    async def digest_callback(self, query: CallbackQuery) -> None:
        if not self.authorized(query.from_user.id):
            await query.answer("Доступ закрыт", show_alert=True)
            return
        await query.answer()
        hours = int((query.data or "digest:24").split(":", 1)[1])
        if query.message:
            await self.send_digest(query.bot, query.message.chat.id, hours)

    async def send_digest(self, bot: Bot, chat_id: int, hours: int) -> None:
        since = datetime.now(UTC) - timedelta(hours=hours)
        messages = await self.database.recent_messages(since.isoformat())
        title = "Сводка за 7 дней" if hours == 168 else f"Сводка за {hours} ч."
        for chunk in digest(messages, title, self.settings.timezone):
            await bot.send_message(chat_id, chunk)

    async def status(self, message: Message) -> None:
        if not self.authorized(message.from_user.id if message.from_user else None):
            return
        rows = await self.database.sync_status()
        states = {row["account_id"]: row for row in rows}
        lines = ["<b>Состояние синхронизации</b>"]
        for account in self.accounts:
            state = states.get(account.id)
            if not state:
                marker, details = "⚪️", "ещё не проверялся"
            elif state["last_error"]:
                marker, details = "🔴", escape(str(state["last_error"]))
            else:
                marker, details = "🟢", f"обновлено {escape(str(state['updated_at']))} UTC"
            lines.append(f"{marker} <code>{escape(account.email)}</code> — {details}")
        await message.answer("\n".join(lines))

    async def accounts_command(self, message: Message) -> None:
        if not self.authorized(message.from_user.id if message.from_user else None):
            return
        lines = [f"<b>Подключено ящиков: {len(self.accounts)}</b>"]
        lines.extend(f"• <code>{escape(account.email)}</code> ({account.provider})" for account in self.accounts)
        await message.answer("\n".join(lines))


def build_dispatcher(settings: Settings, database: Database, accounts: list[Account]) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(BotHandlers(settings, database, accounts).router)
    return dispatcher

