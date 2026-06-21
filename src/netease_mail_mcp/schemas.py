from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AttachmentMetadata:
    filename: Optional[str]
    content_type: str
    size: Optional[int]
    content_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EmailSearchResult:
    email_id: str
    message_id: Optional[str]
    subject: str
    from_: str
    to: List[str]
    cc: List[str]
    date: Optional[str]
    snippet: str
    has_attachments: bool
    attachment_count: int

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["from"] = data.pop("from_")
        return data


@dataclass
class MailboxInfo:
    name: str
    select_name: str
    delimiter: Optional[str]
    flags: List[str]
    role: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EmailContent:
    email_id: str
    message_id: Optional[str]
    in_reply_to: Optional[str]
    references: List[str]
    subject: str
    from_: str
    to: List[str]
    cc: List[str]
    bcc: List[str]
    date: Optional[str]
    plain_text: str
    html_text_converted_to_text: str
    snippet: str
    attachments: List[AttachmentMetadata] = field(default_factory=list)
    raw_headers: Dict[str, Optional[str]] = field(default_factory=dict)
    quoted_text_removed: str = "unknown"
    warnings: List[str] = field(default_factory=list)

    def body_text(self) -> str:
        return self.plain_text or self.html_text_converted_to_text

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["from"] = data.pop("from_")
        data["attachments"] = [item.to_dict() for item in self.attachments]
        return data


@dataclass
class ThreadMessage:
    email_id: str
    message_id: Optional[str]
    in_reply_to: Optional[str]
    references: List[str]
    subject: str
    from_: str
    to: List[str]
    cc: List[str]
    date: Optional[str]
    body_text: str
    quoted_text_removed: str
    attachments_metadata: List[AttachmentMetadata] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["from"] = data.pop("from_")
        data["attachments_metadata"] = [
            item.to_dict() for item in self.attachments_metadata
        ]
        return data


@dataclass
class ThreadJSON:
    thread_id: str
    root_subject: str
    participants: List[str]
    message_count: int
    messages: List[ThreadMessage]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "root_subject": self.root_subject,
            "participants": self.participants,
            "message_count": self.message_count,
            "messages": [message.to_dict() for message in self.messages],
            "warnings": self.warnings,
        }


@dataclass
class ReplyMatch:
    email_id: str
    mailbox: str
    message_id: Optional[str]
    subject: str
    to: List[str]
    cc: List[str]
    date: Optional[str]
    match_method: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InboxReplyStatus:
    email_id: str
    mailbox: str
    message_id: Optional[str]
    subject: str
    from_: str
    to: List[str]
    cc: List[str]
    date: Optional[str]
    replied: bool
    reply_count: int
    latest_reply_date: Optional[str]
    replies: List[ReplyMatch] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["from"] = data.pop("from_")
        data["replies"] = [item.to_dict() for item in self.replies]
        return data


@dataclass
class InboxReplyStatusReport:
    inbox_mailbox: str
    sent_mailbox: str
    checked_count: int
    replied_count: int
    unreplied_count: int
    items: List[InboxReplyStatus]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inbox_mailbox": self.inbox_mailbox,
            "sent_mailbox": self.sent_mailbox,
            "checked_count": self.checked_count,
            "replied_count": self.replied_count,
            "unreplied_count": self.unreplied_count,
            "items": [item.to_dict() for item in self.items],
            "warnings": self.warnings,
        }
