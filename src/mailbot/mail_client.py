import email
import imaplib
import re
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from mailbot.models import Account, MailMessage


MAX_MESSAGE_BYTES = 131_072


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif tag in {"p", "div", "br", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        decoded = str(make_header(decode_header(value)))
        return re.sub(r"\s+", " ", decoded.replace("\xa0", " ")).strip()
    except (LookupError, UnicodeDecodeError):
        return value


def _payload_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _extract_body(message: Message) -> str:
    plain: list[str] = []
    html: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        disposition = (part.get("Content-Disposition") or "").casefold()
        if "attachment" in disposition:
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            plain.append(_payload_text(part))
        elif content_type == "text/html":
            html.append(_payload_text(part))

    text = "\n".join(plain).strip()
    if not text and html:
        parser = _HTMLTextExtractor()
        parser.feed("\n".join(html))
        text = parser.text()
    return re.sub(r"[ \t]+", " ", text)[:20_000]


def _received_at(message: Message) -> datetime:
    try:
        parsed = parsedate_to_datetime(message.get("Date", ""))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return datetime.now(UTC)


class ImapClient:
    def __init__(self, account: Account):
        self.account = account

    def fetch_new(
        self,
        previous_state: tuple[str, int] | None,
        first_sync_hours: int,
    ) -> tuple[str, int, bool, list[MailMessage]]:
        with imaplib.IMAP4_SSL(self.account.host, 993, timeout=45) as client:
            client.login(self.account.email, self.account.password)
            status, _ = client.select(self.account.folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Не удалось открыть папку {self.account.folder}")

            uidvalidity = self._uidvalidity(client)
            is_initial = previous_state is None or previous_state[0] != uidvalidity
            if is_initial:
                since = datetime.now(UTC) - timedelta(hours=first_sync_hours)
                status, data = client.uid("search", None, "SINCE", since.strftime("%d-%b-%Y"))
                last_known_uid = 0
            else:
                last_known_uid = previous_state[1]
                status, data = client.uid("search", None, "UID", f"{last_known_uid + 1}:*")

            if status != "OK":
                raise RuntimeError("IMAP SEARCH завершился с ошибкой")

            uids = [int(item) for item in data[0].split() if item.isdigit()]
            uids = [uid for uid in uids if uid > last_known_uid]
            messages: list[MailMessage] = []
            for uid in uids:
                parsed = self._fetch_message(client, uid, uidvalidity)
                if parsed:
                    messages.append(parsed)

            baseline_uid = self._uidnext(client) - 1 if is_initial else last_known_uid
            highest_uid = max([max(0, baseline_uid), *uids])
            return uidvalidity, highest_uid, is_initial, messages

    @staticmethod
    def _uidvalidity(client: imaplib.IMAP4_SSL) -> str:
        response = client.response("UIDVALIDITY")[1]
        if response and response[0]:
            value = response[0]
            return value.decode() if isinstance(value, bytes) else str(value)
        return "unknown"

    @staticmethod
    def _uidnext(client: imaplib.IMAP4_SSL) -> int:
        response = client.response("UIDNEXT")[1]
        if response and response[0]:
            value = response[0]
            try:
                return int(value.decode() if isinstance(value, bytes) else value)
            except (TypeError, ValueError):
                pass
        return 1

    def _fetch_message(
        self,
        client: imaplib.IMAP4_SSL,
        uid: int,
        uidvalidity: str,
    ) -> MailMessage | None:
        status, data = client.uid("fetch", str(uid), f"(BODY.PEEK[]<0.{MAX_MESSAGE_BYTES}>)")
        if status != "OK":
            return None
        chunks = [item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)]
        if not chunks:
            return None

        parsed = email.message_from_bytes(b"".join(chunks))
        sender_name, sender_address = parseaddr(_decode_header(parsed.get("From")))
        sender = f"{sender_name} <{sender_address}>" if sender_name else sender_address
        headers = {
            "list-unsubscribe": parsed.get("List-Unsubscribe", ""),
            "precedence": parsed.get("Precedence", ""),
            "auto-submitted": parsed.get("Auto-Submitted", ""),
        }
        return MailMessage(
            account_id=self.account.id,
            account_email=self.account.email,
            uidvalidity=uidvalidity,
            uid=uid,
            message_id=parsed.get("Message-ID", f"{self.account.id}:{uidvalidity}:{uid}"),
            sender=sender or "Неизвестный отправитель",
            subject=_decode_header(parsed.get("Subject")) or "Без темы",
            received_at=_received_at(parsed),
            body=_extract_body(parsed),
            headers=headers,
        )
