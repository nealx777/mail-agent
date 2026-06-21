from __future__ import annotations

import imaplib
import logging
import re
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Iterable, List, Optional

from .config import Settings
from .email_parser import (
    BodyPart,
    build_email_content,
    build_search_result,
    decode_body_part,
    normalize_subject,
    parse_address_list,
    parse_bodystructure,
    parse_headers,
)
from .schemas import EmailContent, EmailSearchResult, MailboxInfo

LOGGER = logging.getLogger(__name__)


class NeteaseMailClient(AbstractContextManager["NeteaseMailClient"]):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "NeteaseMailClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        if self.conn:
            return
        if self.settings.imap_ssl:
            conn: imaplib.IMAP4 | imaplib.IMAP4_SSL = imaplib.IMAP4_SSL(
                self.settings.imap_host, self.settings.imap_port
            )
        else:
            conn = imaplib.IMAP4(self.settings.imap_host, self.settings.imap_port)
        conn.login(self.settings.email_username, self.settings.email_password)
        self.conn = conn
        LOGGER.info("IMAP 登录成功：host=%s username=%s", self.settings.imap_host, self.settings.email_username)

    def close(self) -> None:
        if not self.conn:
            return
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.conn.logout()
        except Exception:
            pass
        self.conn = None

    def test_connection(self, mailbox: str = "INBOX") -> dict:
        self._select_readonly(mailbox)
        status, data = self._conn().status(_mailbox_arg(mailbox), "(MESSAGES UNSEEN)")
        if status != "OK":
            raise RuntimeError(f"IMAP STATUS 失败：{status}")
        return {
            "ok": True,
            "mailbox": mailbox,
            "imap_host": self.settings.imap_host,
            "status": _decode_status(data),
        }

    def list_mailboxes(self) -> List[MailboxInfo]:
        status, data = self._conn().list()
        if status != "OK":
            raise RuntimeError(f"IMAP LIST 失败：{status}")
        mailboxes = []
        for item in data or []:
            if not isinstance(item, bytes):
                continue
            parsed = _parse_list_mailbox(item)
            if parsed:
                mailboxes.append(parsed)
        return mailboxes

    def search_email(
        self,
        query: Optional[str] = None,
        from_email: Optional[str] = None,
        subject: Optional[str] = None,
        since: Optional[str] = None,
        before: Optional[str] = None,
        mailbox: str = "INBOX",
        limit: int = 20,
    ) -> List[EmailSearchResult]:
        limit = max(1, min(limit, 100))
        if not since:
            since_date = date.today() - timedelta(days=self.settings.search_default_days)
            since = since_date.isoformat()

        self._select_readonly(mailbox)
        uids = self._search_uids(since=since, before=before)
        results: List[EmailSearchResult] = []
        max_scan = max(limit * 8, 80)

        for uid in reversed(uids[-max_scan:]):
            header = self.fetch_header(uid)
            parts = self.fetch_bodystructure(uid)
            snippet = self._fetch_first_text_snippet(parts, uid)
            result = build_search_result(uid, header, parts, snippet)
            if not _matches_filters(result, query=query, from_email=from_email, subject=subject):
                continue
            LOGGER.debug(
                "搜索命中：uid=%s message_id=%s subject=%s date=%s",
                result.email_id,
                result.message_id,
                result.subject,
                result.date,
            )
            results.append(result)
            if len(results) >= limit:
                break
        return results

    def read_email(
        self,
        email_id: str,
        mailbox: str = "INBOX",
        include_body: bool = True,
        include_attachment_metadata: bool = True,
    ) -> EmailContent:
        self._select_readonly(mailbox)
        header = self.fetch_header(email_id)
        parts = self.fetch_bodystructure(email_id)
        plain_text = ""
        html_text = ""
        if include_body:
            for part in parts:
                if not part.is_text or part.is_attachment:
                    continue
                raw = self.fetch_section(email_id, part.part_number)
                decoded = decode_body_part(raw, part)
                if part.content_type == "text/plain":
                    plain_text += "\n\n" + decoded
                elif part.content_type == "text/html":
                    html_text += "\n\n" + decoded
        content = build_email_content(
            email_id=email_id,
            raw_header=header,
            parts=parts,
            plain_text=plain_text,
            html_text=html_text,
            include_body=include_body,
            include_attachment_metadata=include_attachment_metadata,
        )
        LOGGER.debug(
            "读取邮件：uid=%s message_id=%s subject=%s date=%s",
            content.email_id,
            content.message_id,
            content.subject,
            content.date,
        )
        return content

    def fetch_header(self, uid: str) -> bytes:
        return self._fetch_payload(uid, "(BODY.PEEK[HEADER])")

    def fetch_section(self, uid: str, section: str) -> bytes:
        return self._fetch_payload(uid, f"(BODY.PEEK[{section}])")

    def fetch_bodystructure(self, uid: str) -> List[BodyPart]:
        status, data = self._conn().uid("fetch", uid, "(BODYSTRUCTURE)")
        if status != "OK":
            raise RuntimeError(f"读取 BODYSTRUCTURE 失败：uid={uid} status={status}")
        raw = _extract_bodystructure(data)
        if not raw:
            return []
        return parse_bodystructure(raw)

    def candidate_uids(
        self,
        mailbox: str,
        since: str,
        before: Optional[str] = None,
        max_count: int = 500,
    ) -> List[str]:
        self._select_readonly(mailbox)
        uids = self._search_uids(since=since, before=before)
        return uids[-max_count:]

    def _search_uids(self, since: Optional[str], before: Optional[str]) -> List[str]:
        criteria = ["ALL"]
        if since:
            criteria.extend(["SINCE", _imap_date(since)])
        if before:
            criteria.extend(["BEFORE", _imap_date(before)])
        status, data = self._conn().uid("search", None, *criteria)
        if status != "OK":
            raise RuntimeError(f"IMAP 搜索失败：{status}")
        raw = data[0] if data else b""
        return [item.decode("ascii") for item in raw.split() if item]

    def _fetch_payload(self, uid: str, query: str) -> bytes:
        status, data = self._conn().uid("fetch", uid, query)
        if status != "OK":
            raise RuntimeError(f"IMAP FETCH 失败：uid={uid} query={query} status={status}")
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
        return b""

    def _fetch_first_text_snippet(self, parts: Iterable[BodyPart], uid: str) -> str:
        for part in parts:
            if part.is_text and not part.is_attachment:
                raw = self.fetch_section(uid, part.part_number)
                return decode_body_part(raw, part)
        return ""

    def _select_readonly(self, mailbox: str) -> None:
        # readonly=True 会使用 EXAMINE/只读选择，避免设置已读等副作用。
        status, _ = self._conn().select(_mailbox_arg(mailbox), readonly=True)
        if status != "OK":
            raise RuntimeError(f"只读打开邮箱失败：mailbox={mailbox} status={status}")

    def _conn(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        if not self.conn:
            raise RuntimeError("IMAP 尚未连接。")
        return self.conn


def _imap_date(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return parsed.strftime("%d-%b-%Y")


def _decode_status(data: list[bytes]) -> str:
    return " ".join(item.decode("utf-8", errors="replace") for item in data or [])


def _mailbox_arg(mailbox: str) -> str:
    if mailbox.upper() == "INBOX":
        return mailbox
    if len(mailbox) >= 2 and mailbox[0] == '"' and mailbox[-1] == '"':
        return mailbox
    if re.search(r'[\s"\\()]', mailbox):
        escaped = mailbox.replace("\\", "\\\\").replace('"', r"\"")
        return f'"{escaped}"'
    return mailbox


def _parse_list_mailbox(raw: bytes) -> Optional[MailboxInfo]:
    # LIST 响应示例：(\HasNoChildren \Sent) "/" "&XfJT0ZAB-"
    text = raw.decode("utf-8", errors="replace")
    match = re.match(r"^\((?P<flags>.*?)\)\s+(?P<delimiter>NIL|\".*?\")\s+(?P<name>.+)$", text)
    if not match:
        return None

    flags = [item for item in match.group("flags").split() if item]
    delimiter = _unquote_imap_atom(match.group("delimiter"))
    if delimiter == "NIL":
        delimiter = None
    select_name = _unquote_imap_atom(match.group("name"))
    display_name = _decode_modified_utf7(select_name)
    return MailboxInfo(
        name=display_name,
        select_name=select_name,
        delimiter=delimiter,
        flags=flags,
        role=_infer_mailbox_role(display_name, flags),
    )


def _unquote_imap_atom(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace(r"\"", '"').replace(r"\\", "\\")
    return value


def _decode_modified_utf7(value: str) -> str:
    # IMAP 的非 ASCII 目录名使用 modified UTF-7；select 时仍使用原始编码名。
    result = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "&":
            result.append(char)
            index += 1
            continue
        end = value.find("-", index)
        if end < 0:
            result.append(char)
            index += 1
            continue
        token = value[index + 1 : end]
        if token == "":
            result.append("&")
        else:
            result.append(_decode_modified_utf7_token(token))
        index = end + 1
    return "".join(result)


def _decode_modified_utf7_token(token: str) -> str:
    import base64

    padded = token.replace(",", "/")
    padded += "=" * ((4 - len(padded) % 4) % 4)
    try:
        return base64.b64decode(padded).decode("utf-16-be")
    except Exception:
        return "&" + token + "-"


def _infer_mailbox_role(name: str, flags: List[str]) -> Optional[str]:
    lowered_flags = {flag.lower() for flag in flags}
    lowered_name = name.lower()
    if "\\inbox" in lowered_flags or lowered_name == "inbox":
        return "inbox"
    if "\\sent" in lowered_flags or lowered_name in {"sent", "sent messages", "已发送", "已发送邮件"}:
        return "sent"
    if "\\drafts" in lowered_flags or "draft" in lowered_name or "草稿" in lowered_name:
        return "drafts"
    if "\\trash" in lowered_flags or "trash" in lowered_name or "deleted" in lowered_name or "已删除" in lowered_name:
        return "trash"
    if "\\junk" in lowered_flags or "junk" in lowered_name or "spam" in lowered_name or "垃圾" in lowered_name:
        return "junk"
    return None


def _extract_bodystructure(data: list) -> bytes:
    joined = b" ".join(
        item if isinstance(item, bytes) else item[0] if isinstance(item, tuple) else b""
        for item in data
    )
    marker = b"BODYSTRUCTURE "
    start = joined.find(marker)
    if start < 0:
        return b""
    start = joined.find(b"(", start + len(marker))
    if start < 0:
        return b""

    depth = 0
    in_quote = False
    escaped = False
    for index in range(start, len(joined)):
        char = joined[index]
        if in_quote:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                in_quote = False
            continue
        if char == 34:
            in_quote = True
        elif char == 40:
            depth += 1
        elif char == 41:
            depth -= 1
            if depth == 0:
                return joined[start : index + 1]
    return b""


def _matches_filters(
    result: EmailSearchResult,
    query: Optional[str],
    from_email: Optional[str],
    subject: Optional[str],
) -> bool:
    haystack = " ".join(
        [
            result.subject,
            result.from_,
            " ".join(result.to),
            " ".join(result.cc),
            result.snippet,
        ]
    ).lower()
    if query and query.lower() not in haystack:
        return False
    if from_email and from_email.lower() not in result.from_.lower():
        return False
    if subject and subject.lower() not in result.subject.lower():
        return False
    return True


def participant_keys(content: EmailContent) -> set[str]:
    values = [content.from_, *content.to, *content.cc]
    result = set()
    for value in values:
        for address in parse_address_list(value):
            result.add(address.lower())
        match = re.search(r"<([^>]+)>", value)
        if match:
            result.add(match.group(1).lower())
        elif "@" in value:
            result.add(value.lower())
    return result


def email_timestamp(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        return parsedate_to_datetime(value).timestamp()
    except Exception:
        try:
            return datetime.fromisoformat(value).timestamp()
        except Exception:
            return 0.0


def normalized_subject_from_header(raw_header: bytes) -> str:
    headers = parse_headers(raw_header)
    return normalize_subject(headers.get("Subject") or "")
