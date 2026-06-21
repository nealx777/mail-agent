from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Protocol

from .email_parser import normalize_subject, parse_address_list
from .imap_client import email_timestamp
from .schemas import EmailContent, InboxReplyStatus, InboxReplyStatusReport, ReplyMatch


class ReplyStatusClient(Protocol):
    def search_email(
        self,
        query: Optional[str] = None,
        from_email: Optional[str] = None,
        subject: Optional[str] = None,
        since: Optional[str] = None,
        before: Optional[str] = None,
        mailbox: str = "INBOX",
        limit: int = 20,
    ):
        ...

    def read_email(
        self,
        email_id: str,
        mailbox: str = "INBOX",
        include_body: bool = True,
        include_attachment_metadata: bool = True,
    ) -> EmailContent:
        ...

    def candidate_uids(
        self,
        mailbox: str,
        since: str,
        before: Optional[str] = None,
        max_count: int = 500,
    ) -> List[str]:
        ...


def get_inbox_reply_status(
    client: ReplyStatusClient,
    inbox_mailbox: str = "INBOX",
    sent_mailbox: str = "Sent",
    since: Optional[str] = None,
    before: Optional[str] = None,
    sent_since: Optional[str] = None,
    sent_before: Optional[str] = None,
    query: Optional[str] = None,
    from_email: Optional[str] = None,
    subject: Optional[str] = None,
    limit: int = 50,
    sent_scan_limit: int = 1000,
) -> InboxReplyStatusReport:
    limit = max(1, min(limit, 200))
    sent_scan_limit = max(50, min(sent_scan_limit, 5000))

    inbox_results = client.search_email(
        query=query,
        from_email=from_email,
        subject=subject,
        since=since,
        before=before,
        mailbox=inbox_mailbox,
        limit=limit,
    )
    inbox_messages = [
        client.read_email(
            item.email_id,
            mailbox=inbox_mailbox,
            include_body=False,
            include_attachment_metadata=False,
        )
        for item in inbox_results
    ]

    warnings: List[str] = []
    if not inbox_messages:
        return InboxReplyStatusReport(
            inbox_mailbox=inbox_mailbox,
            sent_mailbox=sent_mailbox,
            checked_count=0,
            replied_count=0,
            unreplied_count=0,
            items=[],
            warnings=["未找到符合条件的收件箱邮件。"],
        )

    sent_window_start = sent_since or _earliest_message_day(inbox_messages) or _default_since()
    sent_uids = client.candidate_uids(
        mailbox=sent_mailbox,
        since=sent_window_start,
        before=sent_before,
        max_count=sent_scan_limit,
    )
    sent_messages = [
        client.read_email(
            uid,
            mailbox=sent_mailbox,
            include_body=False,
            include_attachment_metadata=False,
        )
        for uid in sent_uids
    ]

    items = [
        _status_for_inbox_message(
            inbox_message,
            sent_messages,
            inbox_mailbox=inbox_mailbox,
            sent_mailbox=sent_mailbox,
        )
        for inbox_message in inbox_messages
    ]

    replied_count = sum(1 for item in items if item.replied)
    if len(sent_uids) >= sent_scan_limit:
        warnings.append(
            f"已发送目录候选邮件达到扫描上限 {sent_scan_limit}，较旧回复可能未被纳入。"
        )

    return InboxReplyStatusReport(
        inbox_mailbox=inbox_mailbox,
        sent_mailbox=sent_mailbox,
        checked_count=len(items),
        replied_count=replied_count,
        unreplied_count=len(items) - replied_count,
        items=items,
        warnings=warnings,
    )


def _status_for_inbox_message(
    inbox_message: EmailContent,
    sent_messages: Iterable[EmailContent],
    inbox_mailbox: str,
    sent_mailbox: str,
) -> InboxReplyStatus:
    matches: List[ReplyMatch] = []
    warnings: List[str] = []
    seen = set()

    for sent_message in sent_messages:
        method = _match_reply(inbox_message, sent_message)
        if not method:
            continue
        key = (sent_mailbox, sent_message.email_id)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            ReplyMatch(
                email_id=sent_message.email_id,
                mailbox=sent_mailbox,
                message_id=sent_message.message_id,
                subject=sent_message.subject,
                to=sent_message.to,
                cc=sent_message.cc,
                date=sent_message.date,
                match_method=method,
            )
        )

    matches.sort(key=lambda item: email_timestamp(item.date))
    if not inbox_message.message_id:
        warnings.append("该收件箱邮件缺少 Message-ID，回复判断可能只能依赖弱规则。")
    if any(item.match_method.startswith("fallback") for item in matches):
        warnings.append("存在通过主题、收件人和时间推断的回复，可能需要人工复核。")

    latest_reply_date = matches[-1].date if matches else None
    return InboxReplyStatus(
        email_id=inbox_message.email_id,
        mailbox=inbox_mailbox,
        message_id=inbox_message.message_id,
        subject=inbox_message.subject,
        from_=inbox_message.from_,
        to=inbox_message.to,
        cc=inbox_message.cc,
        date=inbox_message.date,
        replied=bool(matches),
        reply_count=len(matches),
        latest_reply_date=latest_reply_date,
        replies=matches,
        warnings=warnings,
    )


def _match_reply(inbox_message: EmailContent, sent_message: EmailContent) -> Optional[str]:
    if not _sent_after_inbox(inbox_message, sent_message):
        return None

    if inbox_message.message_id and sent_message.in_reply_to == inbox_message.message_id:
        return "direct_in_reply_to"
    if inbox_message.message_id and inbox_message.message_id in sent_message.references:
        return "direct_references"

    inbox_ids = _message_ids(inbox_message)
    sent_ids = _message_ids(sent_message)
    if inbox_ids.intersection(sent_ids):
        return "direct_thread_headers"

    if _fallback_subject_and_recipient_match(inbox_message, sent_message):
        return "fallback_subject_recipient_time"
    return None


def _message_ids(message: EmailContent) -> set[str]:
    values = set(message.references)
    if message.message_id:
        values.add(message.message_id)
    if message.in_reply_to:
        values.add(message.in_reply_to)
    return {item for item in values if item}


def _fallback_subject_and_recipient_match(
    inbox_message: EmailContent,
    sent_message: EmailContent,
) -> bool:
    if normalize_subject(inbox_message.subject) != normalize_subject(sent_message.subject):
        return False
    inbox_senders = _addresses([inbox_message.from_])
    sent_recipients = _addresses([*sent_message.to, *sent_message.cc, *sent_message.bcc])
    return bool(inbox_senders.intersection(sent_recipients))


def _addresses(values: Iterable[str]) -> set[str]:
    result = set()
    for value in values:
        for address in parse_address_list(value):
            result.add(address.lower())
    return result


def _sent_after_inbox(inbox_message: EmailContent, sent_message: EmailContent) -> bool:
    inbox_ts = email_timestamp(inbox_message.date)
    sent_ts = email_timestamp(sent_message.date)
    if not inbox_ts or not sent_ts:
        return True
    return sent_ts >= inbox_ts


def _earliest_message_day(messages: Iterable[EmailContent]) -> Optional[str]:
    timestamps = [email_timestamp(message.date) for message in messages]
    timestamps = [item for item in timestamps if item]
    if not timestamps:
        return None
    dt = datetime.fromtimestamp(min(timestamps)).date()
    return (dt - timedelta(days=1)).isoformat()


def _default_since() -> str:
    return (date.today() - timedelta(days=30)).isoformat()
