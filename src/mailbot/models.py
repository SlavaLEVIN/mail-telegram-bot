from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    email: str
    provider: str
    password: str = field(repr=False)
    folder: str = "INBOX"

    @property
    def host(self) -> str:
        return {
            "gmail": "imap.gmail.com",
            "mailru": "imap.mail.ru",
        }[self.provider]


@dataclass(frozen=True, slots=True)
class MailMessage:
    account_id: str
    account_email: str
    uidvalidity: str
    uid: int
    message_id: str
    sender: str
    subject: str
    received_at: datetime
    body: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class Classification:
    category: str
    importance: int
    summary: str
    source: str


@dataclass(frozen=True, slots=True)
class StoredMessage:
    account_id: str
    account_email: str
    sender: str
    subject: str
    received_at: datetime
    category: str
    importance: int
    summary: str

