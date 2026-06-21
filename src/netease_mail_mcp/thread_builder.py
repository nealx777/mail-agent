from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import List, Optional

from .email_parser import normalize_subject
from .imap_client import NeteaseMailClient, email_timestamp, participant_keys
from .schemas import EmailContent, ThreadJSON, ThreadMessage


def get_full_thread(
    client: NeteaseMailClient,
    email_id: str,
    mailbox: str = "INBOX",
    lookback_days: int = 90,
    include_attachment_metadata: bool = True,
) -> ThreadJSON:
    seed = client.read_email(
        email_id,
        mailbox=mailbox,
        include_body=True,
        include_attachment_metadata=include_attachment_metadata,
    )
    seed_subject = normalize_subject(seed.subject)
    seed_ids = _message_id_set(seed)
    seed_participants = participant_keys(seed)
    warnings: List[str] = []

    since = _window_start(seed.date, lookback_days)
    candidates = client.candidate_uids(mailbox=mailbox, since=since, max_count=800)
    matched: dict[str, EmailContent] = {seed.email_id: seed}

    for uid in candidates:
        if uid == email_id:
            continue
        # 先只读取头部和结构；命中后再读取正文，降低无关邮件读取量。
        candidate = client.read_email(
            uid,
            mailbox=mailbox,
            include_body=False,
            include_attachment_metadata=include_attachment_metadata,
        )
        if _matches_by_header(seed, candidate, seed_ids):
            matched[uid] = client.read_email(
                uid,
                mailbox=mailbox,
                include_body=True,
                include_attachment_metadata=include_attachment_metadata,
            )
            continue
        if _matches_by_subject_and_participants(seed_subject, seed_participants, candidate):
            matched[uid] = client.read_email(
                uid,
                mailbox=mailbox,
                include_body=True,
                include_attachment_metadata=include_attachment_metadata,
            )
            warnings.append(
                f"邮件 uid={uid} 通过主题和参与人推断为同一线程，可能存在误判。"
            )

    messages = sorted(
        [_to_thread_message(item) for item in matched.values()],
        key=lambda message: email_timestamp(message.date),
    )
    participants = sorted(_collect_participants(matched.values()))

    if not seed.message_id:
        warnings.append("根邮件缺少 Message-ID，线程重建可能不完整。")
    if not seed.references and not seed.in_reply_to:
        warnings.append("根邮件缺少 References/In-Reply-To，只能依赖主题和参与人辅助判断。")
    if any(message.attachments_metadata for message in messages):
        warnings.append("线程中存在附件；第一版只读取附件元信息，未分析附件内容。")
    if len(messages) == 1:
        warnings.append("只找到当前邮件；可能是单封邮件，也可能是线程头信息缺失导致未能完整重建。")

    thread_id = _thread_id(seed)
    return ThreadJSON(
        thread_id=thread_id,
        root_subject=seed.subject,
        participants=participants,
        message_count=len(messages),
        messages=messages,
        warnings=_dedupe(warnings + seed.warnings),
    )


def _message_id_set(content: EmailContent) -> set[str]:
    ids = set(content.references)
    if content.message_id:
        ids.add(content.message_id)
    if content.in_reply_to:
        ids.add(content.in_reply_to)
    return {item for item in ids if item}


def _matches_by_header(seed: EmailContent, candidate: EmailContent, seed_ids: set[str]) -> bool:
    candidate_ids = _message_id_set(candidate)
    if seed.message_id and candidate.in_reply_to == seed.message_id:
        return True
    if candidate.message_id and candidate.message_id in seed.references:
        return True
    if seed.message_id and seed.message_id in candidate.references:
        return True
    return bool(seed_ids.intersection(candidate_ids))


def _matches_by_subject_and_participants(
    seed_subject: str,
    seed_participants: set[str],
    candidate: EmailContent,
) -> bool:
    if not seed_subject or normalize_subject(candidate.subject) != seed_subject:
        return False
    candidate_participants = participant_keys(candidate)
    return bool(seed_participants.intersection(candidate_participants))


def _window_start(date_value: Optional[str], lookback_days: int) -> str:
    lookback_days = max(1, min(lookback_days, 365))
    if date_value:
        try:
            dt = datetime.fromisoformat(date_value)
            return (dt.date() - timedelta(days=lookback_days)).isoformat()
        except Exception:
            pass
    return (datetime.today().date() - timedelta(days=lookback_days)).isoformat()


def _to_thread_message(content: EmailContent) -> ThreadMessage:
    return ThreadMessage(
        email_id=content.email_id,
        message_id=content.message_id,
        in_reply_to=content.in_reply_to,
        references=content.references,
        subject=content.subject,
        from_=content.from_,
        to=content.to,
        cc=content.cc,
        date=content.date,
        body_text=content.body_text(),
        quoted_text_removed=content.quoted_text_removed,
        attachments_metadata=content.attachments,
    )


def _collect_participants(messages) -> set[str]:
    result = set()
    for message in messages:
        result.update(participant_keys(message))
    return result


def _thread_id(seed: EmailContent) -> str:
    base = seed.message_id or normalize_subject(seed.subject) or seed.email_id
    digest = hashlib.sha256(base.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"thread_{digest}"


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
