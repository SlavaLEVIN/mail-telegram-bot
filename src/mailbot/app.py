import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from mailbot.bot import BotHandlers, build_dispatcher
from mailbot.classifier import AiClassifier, Classifier, RuleClassifier
from mailbot.config import Settings, load_accounts
from mailbot.database import Database
from mailbot.mail_client import ImapClient
from mailbot.models import Account
from mailbot.presentation import notification


LOGGER = logging.getLogger(__name__)


class MailMonitor:
    def __init__(self, settings: Settings, database: Database, bot: Bot, classifier: Classifier):
        self.settings = settings
        self.database = database
        self.bot = bot
        self.classifier = classifier
        self.semaphore = asyncio.Semaphore(settings.poll_concurrency)

    async def run_account(self, account: Account, initial_delay: float) -> None:
        await asyncio.sleep(initial_delay)
        while True:
            try:
                async with self.semaphore:
                    await self.sync_account(account)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.exception("Ошибка синхронизации %s", account.id)
                await self.database.set_sync_error(account.id, str(exc))
            delay = self.settings.poll_interval_seconds + random.uniform(0, 20)
            await asyncio.sleep(delay)

    async def sync_account(self, account: Account) -> None:
        previous_state = await self.database.get_sync_state(account.id)
        result = await asyncio.to_thread(
            ImapClient(account).fetch_new,
            previous_state,
            self.settings.first_sync_hours,
        )
        uidvalidity, highest_uid, is_initial, messages = result
        cutoff = datetime.now(UTC) - timedelta(hours=self.settings.first_sync_hours)

        for message in messages:
            if is_initial and message.received_at < cutoff:
                continue
            classification = await self.classifier.classify(message)
            inserted = await self.database.add_message(message, classification)
            already_notified = await self.database.is_notified(account.id, uidvalidity, message.uid)
            should_notify = (
                not is_initial
                and self.settings.allowed_user_id > 0
                and classification.importance >= self.settings.importance_threshold
                and (inserted or not already_notified)
            )
            if should_notify:
                text = notification(
                    message,
                    classification,
                    message.received_at.astimezone(self.settings.timezone),
                )
                await self.bot.send_message(self.settings.allowed_user_id, text)
                await self.database.mark_notified(account.id, uidvalidity, message.uid)

        await self.database.set_sync_state(account.id, uidvalidity, highest_uid)
        LOGGER.info("%s: обработано новых писем: %d", account.id, len(messages))


async def scheduled_digest(settings: Settings, database: Database, bot: Bot) -> None:
    handlers = BotHandlers(settings, database, [])
    while True:
        now = datetime.now(settings.timezone)
        date_key = now.date().isoformat()
        last_sent = await database.get_app_state("last_digest_date")
        scheduled = now.replace(
            hour=settings.digest_time.hour,
            minute=settings.digest_time.minute,
            second=0,
            microsecond=0,
        )
        if settings.allowed_user_id > 0 and now >= scheduled and last_sent != date_key:
            await handlers.send_digest(bot, settings.allowed_user_id, 24)
            await database.set_app_state("last_digest_date", date_key)
        await asyncio.sleep(30)


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    accounts = load_accounts(settings.accounts_file)
    database = Database(settings.database_path)
    await database.open()

    session = AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None
    bot = Bot(
        settings.telegram_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(settings, database, accounts)
    classifier = Classifier(
        RuleClassifier(settings.important_senders, settings.ignored_senders),
        AiClassifier(settings.openai_api_key, settings.openai_model),
    )
    monitor = MailMonitor(settings, database, bot, classifier)

    tasks = [
        asyncio.create_task(monitor.run_account(account, index * 2.0), name=f"mail:{account.id}")
        for index, account in enumerate(accounts)
    ]
    tasks.append(asyncio.create_task(scheduled_digest(settings, database, bot), name="digest"))

    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await database.close()
        await bot.session.close()
