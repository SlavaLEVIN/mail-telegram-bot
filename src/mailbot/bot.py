from datetime import UTC, datetime, timedelta
from html import escape
from math import ceil

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from mailbot.config import Settings
from mailbot.database import Database
from mailbot.models import Account, StoredMessage
from mailbot.presentation import CATEGORY_LABELS, digest, message_card


PAGE_SIZE = 6
DIGEST_PERIODS = (6, 12, 24, 72, 168)
CATEGORY_BUTTONS = (
    ("💼 Работа", "work"),
    ("🎓 Учёба", "study"),
    ("⏳ Дедлайн", "deadline"),
    ("📅 Встреча", "event"),
    ("👤 Личное", "personal"),
    ("🚨 Безопасность", "security"),
    ("🔐 Код", "code"),
    ("💳 Финансы", "finance"),
    ("📰 Рассылка", "newsletter"),
    ("✉️ Другое", "other"),
)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📬 Письма за 24 часа", callback_data="list:all:24:0")],
            [
                InlineKeyboardButton(text="🔴 Важные", callback_data="list:important:168:0"),
                InlineKeyboardButton(text="🗂 Категории", callback_data="categories"),
            ],
            [
                InlineKeyboardButton(text="📊 Статус", callback_data="status"),
                InlineKeyboardButton(text="📮 Аккаунт", callback_data="accounts"),
            ],
            [InlineKeyboardButton(text="⏰ Автосводка", callback_data="digestcfg")],
        ]
    )


def parse_digest_time(value: str) -> str:
    parts = value.strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("Время нужно написать в формате ЧЧ:ММ, например 08:35")
    hour, minute = (int(part) for part in parts)
    if hour not in range(24) or minute not in range(60):
        raise ValueError("Укажите реальное время от 00:00 до 23:59")
    return f"{hour:02d}:{minute:02d}"


def _period_label(hours: int) -> str:
    return {6: "6 часов", 12: "12 часов", 24: "24 часа", 72: "3 дня", 168: "7 дней"}.get(
        hours, f"{hours} ч."
    )


def notification_keyboard(message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть письмо", callback_data=f"open:{message_id}:important:168:0")],
            [InlineKeyboardButton(text="📬 К письмам", callback_data="list:all:24:0")],
        ]
    )


def _short_subject(message: StoredMessage) -> str:
    label = CATEGORY_LABELS.get(message.category, "✉️").split(" ", 1)[0]
    subject = " ".join(message.subject.split())
    if len(subject) > 38:
        subject = subject[:35] + "…"
    return f"{label} {message.importance} · {subject}"


def _details_keyboard(message_id: int, scope: str, hours: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗂 Категория", callback_data=f"catmenu:{message_id}"),
                InlineKeyboardButton(text="⭐ Важность", callback_data=f"impmenu:{message_id}"),
            ],
            [InlineKeyboardButton(text="← Назад к письмам", callback_data=f"list:{scope}:{hours}:{page}")],
            [InlineKeyboardButton(text="⌂ Главное меню", callback_data="menu")],
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
        self.router.message.register(self.status_command, Command("status"))
        self.router.message.register(self.accounts_command, Command("accounts"))
        self.router.message.register(self.text_input, F.text)
        self.router.callback_query.register(self.callback, F.data)

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
            "<b>Почтовый помощник</b>\n\nВыберите раздел. Следующие экраны будут открываться в этом сообщении.",
            reply_markup=main_menu(),
        )

    async def digest_command(self, message: Message) -> None:
        if self.authorized(message.from_user.id if message.from_user else None):
            await self.send_digest(message.bot, message.chat.id, 24)

    async def status_command(self, message: Message) -> None:
        if self.authorized(message.from_user.id if message.from_user else None):
            await message.answer(await self._status_text(), reply_markup=self._back_menu())

    async def accounts_command(self, message: Message) -> None:
        if self.authorized(message.from_user.id if message.from_user else None):
            await message.answer(self._accounts_text(), reply_markup=self._back_menu())

    async def callback(self, query: CallbackQuery) -> None:
        if not self.authorized(query.from_user.id):
            await query.answer("Доступ закрыт", show_alert=True)
            return
        await query.answer()
        data = query.data or "menu"

        if data == "menu":
            await self._edit(query, "<b>Почтовый помощник</b>\n\nВыберите раздел.", main_menu())
        elif data == "noop":
            return
        elif data == "categories":
            await self._show_categories(query)
        elif data == "status":
            await self._edit(query, await self._status_text(), self._back_menu())
        elif data == "accounts":
            await self._edit(query, self._accounts_text(), self._back_menu())
        elif data == "digestcfg":
            await self._show_digest_settings(query)
        elif data == "dgnow":
            _, hours, _ = await self._digest_settings()
            if query.message:
                await self.send_digest(query.bot, query.message.chat.id, hours)
        elif data == "dgtoggle":
            enabled, _, _ = await self._digest_settings()
            await self.database.set_app_state("digest_enabled", "0" if enabled else "1")
            await self._show_digest_settings(query)
        elif data.startswith("dgperiod:"):
            hours = int(data.split(":", 1)[1])
            if hours in DIGEST_PERIODS:
                await self.database.set_app_state("digest_hours", str(hours))
            await self._show_digest_settings(query)
        elif data.startswith("dgtime:"):
            clock = parse_digest_time(data.split(":", 1)[1])
            await self.database.set_app_state("digest_time", clock)
            await self._show_digest_settings(query)
        elif data == "dgcustom":
            if query.message:
                await self.database.set_app_state("digest_time_input", "1")
                await self.database.set_app_state("digest_panel_message_id", str(query.message.message_id))
                await self._edit(
                    query,
                    "<b>Точное время автосводки</b>\n\nОтправьте время одним сообщением в формате <code>ЧЧ:ММ</code>, например <code>08:35</code>.",
                    InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="digestcfg")]]
                    ),
                )
        elif data.startswith("list:"):
            _, scope, hours, page = data.split(":")
            await self._show_list(query, scope, int(hours), int(page))
        elif data.startswith("open:"):
            _, message_id, scope, hours, page = data.split(":")
            await self._show_message(query, int(message_id), scope, int(hours), int(page))
        elif data.startswith("catmenu:"):
            await self._show_category_editor(query, int(data.split(":")[1]))
        elif data.startswith("impmenu:"):
            await self._show_importance_editor(query, int(data.split(":")[1]))
        elif data.startswith("setcat:"):
            _, message_id, category = data.split(":")
            await self.database.set_category(int(message_id), category)
            await self._show_message(query, int(message_id), "all", 24, 0, "Категория сохранена")
        elif data.startswith("setimp:"):
            _, message_id, importance = data.split(":")
            await self.database.set_importance(int(message_id), int(importance))
            await self._show_message(query, int(message_id), "all", 24, 0, "Важность сохранена")

    async def send_digest(self, bot: Bot, chat_id: int, hours: int) -> None:
        since = datetime.now(UTC) - timedelta(hours=hours)
        messages = await self.database.recent_messages(since.isoformat(), limit=10_000)
        chunks = digest(messages, f"Сводка за {_period_label(hours)}", self.settings.timezone)
        for index, text in enumerate(chunks):
            keyboard = None
            if index == len(chunks) - 1:
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📬 Открыть письма", callback_data=f"list:all:{hours}:0")],
                        [InlineKeyboardButton(text="⚙️ Настроить автосводку", callback_data="digestcfg")],
                    ]
                )
            await bot.send_message(chat_id, text, reply_markup=keyboard)

    async def text_input(self, message: Message) -> None:
        if not self.authorized(message.from_user.id if message.from_user else None):
            return
        if await self.database.get_app_state("digest_time_input") != "1":
            return
        try:
            clock = parse_digest_time(message.text or "")
        except ValueError as exc:
            await message.answer(f"⚠️ {escape(str(exc))}")
            return

        await self.database.set_app_state("digest_time", clock)
        await self.database.set_app_state("digest_time_input", "0")
        panel_id = await self.database.get_app_state("digest_panel_message_id")
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        text, keyboard = await self._digest_payload()
        if panel_id:
            try:
                await message.bot.edit_message_text(
                    text=text,
                    chat_id=message.chat.id,
                    message_id=int(panel_id),
                    reply_markup=keyboard,
                )
                return
            except TelegramBadRequest:
                pass
        await message.answer(text, reply_markup=keyboard)

    async def _show_list(self, query: CallbackQuery, scope: str, hours: int, page: int) -> None:
        text, keyboard = await self._list_payload(scope, hours, page)
        await self._edit(query, text, keyboard)

    async def _list_payload(self, scope: str, hours: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        category = None if scope in {"all", "important"} else scope
        minimum = self.settings.importance_threshold if scope == "important" else None
        messages, total = await self.database.list_messages(
            since.isoformat(),
            limit=PAGE_SIZE,
            offset=page * PAGE_SIZE,
            category=category,
            minimum_importance=minimum,
        )
        page_count = max(1, ceil(total / PAGE_SIZE))
        title = "Важные письма" if scope == "important" else "Письма"
        if category:
            title = CATEGORY_LABELS.get(category, category)
        period = "7 дней" if hours == 168 else f"{hours} ч."
        text = f"<b>{escape(title)}</b> · {period}\nНайдено: {total}\n\nВыберите письмо:"
        if not messages:
            text += "\nПока ничего нет."

        rows = [
            [InlineKeyboardButton(text=_short_subject(item), callback_data=f"open:{item.id}:{scope}:{hours}:{page}")]
            for item in messages
        ]
        navigation: list[InlineKeyboardButton] = []
        if page > 0:
            navigation.append(InlineKeyboardButton(text="←", callback_data=f"list:{scope}:{hours}:{page - 1}"))
        navigation.append(InlineKeyboardButton(text=f"{page + 1}/{page_count}", callback_data="noop"))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(text="→", callback_data=f"list:{scope}:{hours}:{page + 1}"))
        rows.append(navigation)
        rows.append([InlineKeyboardButton(text="⌂ Главное меню", callback_data="menu")])
        return text, InlineKeyboardMarkup(inline_keyboard=rows)

    async def _show_message(
        self,
        query: CallbackQuery,
        message_id: int,
        scope: str,
        hours: int,
        page: int,
        notice: str | None = None,
    ) -> None:
        item = await self.database.get_message(message_id)
        if not item:
            await self._edit(query, "Письмо не найдено.", self._back_menu())
            return
        text = message_card(item, self.settings.timezone)
        if notice:
            text = f"✅ {escape(notice)}\n\n{text}"
        await self._edit(query, text, _details_keyboard(message_id, scope, hours, page))

    async def _show_categories(self, query: CallbackQuery) -> None:
        rows = []
        for index in range(0, len(CATEGORY_BUTTONS), 2):
            rows.append([
                InlineKeyboardButton(text=label, callback_data=f"list:{category}:168:0")
                for label, category in CATEGORY_BUTTONS[index:index + 2]
            ])
        rows.append([InlineKeyboardButton(text="⌂ Главное меню", callback_data="menu")])
        await self._edit(query, "<b>Категории</b>\n\nВыберите категорию писем:", InlineKeyboardMarkup(inline_keyboard=rows))

    async def _digest_settings(self) -> tuple[bool, int, str]:
        enabled = (await self.database.get_app_state("digest_enabled") or "1") == "1"
        raw_hours = await self.database.get_app_state("digest_hours") or "24"
        hours = int(raw_hours) if raw_hours.isdigit() and int(raw_hours) in DIGEST_PERIODS else 24
        default_time = self.settings.digest_time.strftime("%H:%M")
        raw_time = await self.database.get_app_state("digest_time") or default_time
        try:
            clock = parse_digest_time(raw_time)
        except ValueError:
            clock = default_time
        return enabled, hours, clock

    async def _digest_payload(self) -> tuple[str, InlineKeyboardMarkup]:
        enabled, hours, clock = await self._digest_settings()
        status = "включена" if enabled else "выключена"
        text = (
            "<b>Автоматическая сводка</b>\n\n"
            f"Статус: <b>{status}</b>\n"
            f"Период: <b>{_period_label(hours)}</b>\n"
            f"Отправка: <b>{clock}</b> ({escape(str(self.settings.timezone))})\n\n"
            "В сводке будут все письма за период, отсортированные по важности, и краткое описание каждого."
        )
        period_rows = [
            [
                InlineKeyboardButton(
                    text=("✓ " if value == hours else "") + _period_label(value),
                    callback_data=f"dgperiod:{value}",
                )
                for value in DIGEST_PERIODS[:3]
            ],
            [
                InlineKeyboardButton(
                    text=("✓ " if value == hours else "") + _period_label(value),
                    callback_data=f"dgperiod:{value}",
                )
                for value in DIGEST_PERIODS[3:]
            ],
        ]
        time_rows = [
            [InlineKeyboardButton(text=value, callback_data=f"dgtime:{value}") for value in ("08:00", "12:00")],
            [InlineKeyboardButton(text=value, callback_data=f"dgtime:{value}") for value in ("18:00", "21:00")],
        ]
        rows = [
            [InlineKeyboardButton(text="🔕 Выключить" if enabled else "🔔 Включить", callback_data="dgtoggle")],
            [InlineKeyboardButton(text="📝 Прислать сводку сейчас", callback_data="dgnow")],
            *period_rows,
            *time_rows,
            [InlineKeyboardButton(text="✏️ Ввести точное время", callback_data="dgcustom")],
            [InlineKeyboardButton(text="⌂ Главное меню", callback_data="menu")],
        ]
        return text, InlineKeyboardMarkup(inline_keyboard=rows)

    async def _show_digest_settings(self, query: CallbackQuery) -> None:
        await self.database.set_app_state("digest_time_input", "0")
        text, keyboard = await self._digest_payload()
        await self._edit(query, text, keyboard)

    async def _show_category_editor(self, query: CallbackQuery, message_id: int) -> None:
        rows = []
        for index in range(0, len(CATEGORY_BUTTONS), 2):
            rows.append([
                InlineKeyboardButton(text=label, callback_data=f"setcat:{message_id}:{category}")
                for label, category in CATEGORY_BUTTONS[index:index + 2]
            ])
        rows.append([InlineKeyboardButton(text="← К письму", callback_data=f"open:{message_id}:all:24:0")])
        await self._edit(query, "<b>Новая категория</b>", InlineKeyboardMarkup(inline_keyboard=rows))

    async def _show_importance_editor(self, query: CallbackQuery, message_id: int) -> None:
        values = (10, 30, 50, 70, 90, 100)
        rows = [
            [InlineKeyboardButton(text=str(value), callback_data=f"setimp:{message_id}:{value}") for value in values[:3]],
            [InlineKeyboardButton(text=str(value), callback_data=f"setimp:{message_id}:{value}") for value in values[3:]],
            [InlineKeyboardButton(text="← К письму", callback_data=f"open:{message_id}:all:24:0")],
        ]
        await self._edit(
            query,
            "<b>Важность письма</b>\n\n10 — шум, 50 — обычное, 70+ — важное.",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    async def _status_text(self) -> str:
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
        return "\n".join(lines)

    def _accounts_text(self) -> str:
        lines = [f"<b>Подключено ящиков: {len(self.accounts)}</b>"]
        lines.extend(f"• <code>{escape(account.email)}</code>" for account in self.accounts)
        return "\n".join(lines)

    @staticmethod
    def _back_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⌂ Главное меню", callback_data="menu")]])

    @staticmethod
    async def _edit(query: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
        if not query.message:
            return
        try:
            await query.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise


def build_dispatcher(settings: Settings, database: Database, accounts: list[Account]) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(BotHandlers(settings, database, accounts).router)
    return dispatcher
