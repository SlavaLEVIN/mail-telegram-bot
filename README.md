# Telegram-бот для важных писем

Личный бот для нескольких Gmail и Mail.ru аккаунтов. Он проверяет новые письма по IMAP, оценивает важность, присылает важные уведомления и формирует сводку по кнопке или ежедневно в выбранное время.

## Что уже реализовано

- 10 шаблонов Mail.ru и 5 шаблонов Gmail;
- доступ к боту только для одного Telegram ID;
- уведомления о письмах с важностью выше заданного порога;
- команды `/digest`, `/status`, `/accounts`, `/whoami`;
- кнопки сводки за 6 часов, сутки и 7 дней;
- ежедневная сводка по расписанию;
- локальное распознавание кодов и писем безопасности;
- опциональная AI-классификация;
- удаление кодов, секретных строк и ссылок перед отправкой текста в AI;
- хранение только метаданных и резюме — тело письма в SQLite не записывается;
- Docker Compose и автоматический перезапуск.

## 1. Создание бота через BotFather

1. Откройте в Telegram `@BotFather`.
2. Отправьте `/newbot`.
3. Задайте имя и username, заканчивающийся на `bot`.
4. Скопируйте выданный токен в `TELEGRAM_BOT_TOKEN` файла `.env`.

Токен нельзя отправлять в сообщения или добавлять в Git.

## 2. Подготовка Linux Mint

Установите Docker Engine с Compose plugin. Затем в каталоге проекта выполните:

```bash
cp .env.example .env
cp config/accounts.toml.example config/accounts.toml
chmod 600 .env config/accounts.toml
```

Замените адреса в `config/accounts.toml` на настоящие.

## 3. Пароли приложений

Не указывайте обычные пароли от почты.

- Mail.ru: для каждого ящика создайте отдельный пароль внешнего приложения в настройках безопасности.
- Gmail: включите двухэтапную аутентификацию и создайте пароль приложения. Если пункт недоступен в рабочем или учебном аккаунте, его мог отключить администратор.

Внесите пароли в соответствующие переменные `MAILRU_01_PASSWORD` … `GMAIL_05_PASSWORD` файла `.env`.
Если Google показывает пароль группами с пробелами, внесите его без пробелов.

## 4. Определение Telegram ID

Сначала оставьте `ALLOWED_TELEGRAM_USER_ID=0` и запустите бот:

```bash
docker compose up -d --build
docker compose logs -f
```

Напишите боту `/whoami`. Он вернёт числовой ID. Запишите его в `.env`:

```dotenv
ALLOWED_TELEGRAM_USER_ID=123456789
```

Перезапустите контейнер:

```bash
docker compose up -d
```

После этого остальные пользователи не смогут управлять ботом.

### Telegram через Hiddify на Linux Mint

Если прямой доступ к Bot API ограничен, бот может использовать локальный SOCKS5 Hiddify. В `.env` укажите:

```dotenv
TELEGRAM_PROXY_URL=socks5://127.0.0.1:12334
```

`docker-compose.yml` использует `network_mode: host`, поэтому контейнер видит локальный порт хоста. Убедитесь, что Hiddify запущен:

```bash
ss -ltnp | grep 12334
curl -4 -x socks5h://127.0.0.1:12334 -X POST -o /dev/null -w 'HTTP %{http_code}\n' --connect-timeout 10 --max-time 20 'https://api.telegram.org/bot0:invalid/getMe'
```

Ответ `HTTP 401` подтверждает, что маршрут через прокси работает. IMAP-соединения с Gmail и Mail.ru через этот параметр не проксируются.

## 5. AI-классификация

AI необязателен. Без него работают локальные правила для кодов, безопасности, работы, учёбы и рассылок.

Для AI-классификации укажите:

```dotenv
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5-mini
```

Коды, строки с паролями и токенами, а также URL удаляются до обращения к API. Запросы отправляются с `store=false`. Письма с кодами, предупреждения безопасности и очевидные рассылки во внешний AI вообще не передаются.

## Настройка

Основные параметры находятся в `.env`:

```dotenv
POLL_INTERVAL_SECONDS=180
POLL_CONCURRENCY=3
FIRST_SYNC_HOURS=24
IMPORTANCE_THRESHOLD=70
DIGEST_TIME=21:00
TIMEZONE=Europe/Moscow
```

При первом запуске письма за последние 24 часа попадут в базу и сводку, но не вызовут поток уведомлений. Мгновенные уведомления начинаются со следующей проверки.

Для важных или игнорируемых отправителей можно добавить списки через запятую:

```dotenv
IMPORTANT_SENDERS=teacher@university.ru,@important-company.ru
IGNORED_SENDERS=news@example.com,@ads.example
```

## Обслуживание

```bash
docker compose logs -f
docker compose restart
docker compose pull
docker compose up -d --build
```

База находится в `data/mailbot.sqlite3`. Для резервной копии достаточно сохранить этот файл при остановленном контейнере.

## Локальные тесты

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```
