from __future__ import annotations

import email
import html
import re
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Iterable, List, Optional

from bs4 import BeautifulSoup

from .schemas import AttachmentMetadata, EmailContent, EmailSearchResult


MESSAGE_ID_RE = re.compile(r"<[^>]+>")
QUOTE_MARKERS = [
    "\n-----Original Message-----",
    "\nFrom:",
    "\n发件人:",
    "\n在 ",
    "\nOn ",
    "\n原始邮件",
]
SUBJECT_PREFIX_RE = re.compile(
    r"^\s*((re|fw|fwd)\s*:\s*|回复\s*:\s*|转发\s*:\s*)+",
    re.IGNORECASE,
)


@dataclass
class BodyPart:
    part_number: str
    content_type: str
    size: Optional[int]
    filename: Optional[str] = None
    content_id: Optional[str] = None
    disposition: Optional[str] = None
    charset: Optional[str] = None
    encoding: Optional[str] = None
    children: List["BodyPart"] = field(default_factory=list)

    @property
    def is_text(self) -> bool:
        return self.content_type in {"text/plain", "text/html"}

    @property
    def is_attachment(self) -> bool:
        if self.disposition and self.disposition.lower() == "attachment":
            return True
        return bool(self.filename) and not self.is_text


def decode_mime(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def parse_message_ids(value: Optional[str]) -> List[str]:
    if not value:
        return []
    matches = MESSAGE_ID_RE.findall(value)
    return [item.strip() for item in matches] or [value.strip()]


def normalize_subject(subject: str) -> str:
    previous = subject or ""
    current = SUBJECT_PREFIX_RE.sub("", previous).strip()
    while current != previous:
        previous = current
        current = SUBJECT_PREFIX_RE.sub("", previous).strip()
    return re.sub(r"\s+", " ", current).strip().lower()


def parse_address_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    parsed = []
    for name, addr in getaddresses([value]):
        display = decode_mime(name).strip()
        addr = addr.strip()
        if display and addr:
            parsed.append(f"{display} <{addr}>")
        elif addr:
            parsed.append(addr)
        elif display:
            parsed.append(display)
    return parsed


def parse_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except Exception:
        return value


def text_to_snippet(value: str, limit: int = 220) -> str:
    clean = re.sub(r"\s+", " ", value or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def html_to_text(value: str) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = html.unescape(text)
    return normalize_text(text)


def normalize_text(value: str) -> str:
    lines = [line.rstrip() for line in (value or "").replace("\r\n", "\n").split("\n")]
    compact: List[str] = []
    blank_seen = False
    for line in lines:
        if line.strip():
            compact.append(line)
            blank_seen = False
        elif not blank_seen:
            compact.append("")
            blank_seen = True
    return "\n".join(compact).strip()


def strip_probable_quotes(value: str) -> tuple[str, str]:
    """保守去除明显引用；不确定的历史内容会保留给 LLM 判断。"""
    if not value:
        return "", "unknown"

    text = normalize_text(value)
    lines = text.splitlines()
    unquoted = [line for line in lines if not line.lstrip().startswith(">")]
    removed_marker = len(unquoted) != len(lines)
    text = "\n".join(unquoted).strip()

    cut_positions = [text.find(marker) for marker in QUOTE_MARKERS if text.find(marker) > 0]
    if cut_positions:
        text = text[: min(cut_positions)].strip()
        removed_marker = True

    return text, "true" if removed_marker else "unknown"


class _BodyStructureParser:
    def __init__(self, raw: bytes):
        self.text = raw.decode("utf-8", errors="replace")
        self.index = 0

    def parse(self) -> Any:
        self._skip_spaces()
        return self._parse_value()

    def _skip_spaces(self) -> None:
        while self.index < len(self.text) and self.text[self.index].isspace():
            self.index += 1

    def _parse_value(self) -> Any:
        self._skip_spaces()
        if self.index >= len(self.text):
            return None
        char = self.text[self.index]
        if char == "(":
            return self._parse_list()
        if char == '"':
            return self._parse_quoted()
        return self._parse_atom()

    def _parse_list(self) -> List[Any]:
        self.index += 1
        items = []
        while self.index < len(self.text):
            self._skip_spaces()
            if self.index < len(self.text) and self.text[self.index] == ")":
                self.index += 1
                break
            items.append(self._parse_value())
        return items

    def _parse_quoted(self) -> str:
        self.index += 1
        result = []
        while self.index < len(self.text):
            char = self.text[self.index]
            self.index += 1
            if char == "\\" and self.index < len(self.text):
                result.append(self.text[self.index])
                self.index += 1
            elif char == '"':
                break
            else:
                result.append(char)
        return "".join(result)

    def _parse_atom(self) -> Any:
        start = self.index
        while self.index < len(self.text):
            char = self.text[self.index]
            if char.isspace() or char in "()":
                break
            self.index += 1
        atom = self.text[start : self.index]
        if atom.upper() == "NIL":
            return None
        if atom.isdigit():
            return int(atom)
        return atom


def _params_to_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result = {}
    for index in range(0, len(value) - 1, 2):
        key = value[index]
        item = value[index + 1]
        if key is not None and item is not None:
            result[str(key).lower()] = decode_mime(str(item))
    return result


def _disposition(value: Any) -> tuple[Optional[str], dict[str, str]]:
    if not isinstance(value, list) or not value:
        return None, {}
    return str(value[0]).lower() if value[0] else None, _params_to_dict(value[1] if len(value) > 1 else None)


def parse_bodystructure(raw: bytes) -> List[BodyPart]:
    parsed = _BodyStructureParser(raw).parse()
    parts: List[BodyPart] = []

    def walk(node: Any, prefix: str) -> None:
        if not isinstance(node, list) or not node:
            return
        if isinstance(node[0], list):
            index = 0
            while index < len(node) and isinstance(node[index], list):
                child_prefix = f"{prefix}.{index + 1}" if prefix else str(index + 1)
                walk(node[index], child_prefix)
                index += 1
            return

        if len(node) < 7:
            return
        main_type = str(node[0] or "").lower()
        sub_type = str(node[1] or "").lower()
        params = _params_to_dict(node[2] if len(node) > 2 else None)
        content_id = node[3] if len(node) > 3 and node[3] else None
        encoding = str(node[5]).lower() if len(node) > 5 and node[5] else None
        size = node[6] if len(node) > 6 and isinstance(node[6], int) else None

        disposition_name = None
        disposition_params: dict[str, str] = {}
        for extra in node[7:]:
            if isinstance(extra, list) and extra and isinstance(extra[0], str):
                candidate, candidate_params = _disposition(extra)
                if candidate in {"attachment", "inline"}:
                    disposition_name = candidate
                    disposition_params = candidate_params
                    break

        filename = (
            disposition_params.get("filename")
            or params.get("filename")
            or params.get("name")
        )
        parts.append(
            BodyPart(
                part_number=prefix or "1",
                content_type=f"{main_type}/{sub_type}",
                size=size,
                filename=filename,
                content_id=str(content_id) if content_id else None,
                disposition=disposition_name,
                charset=params.get("charset"),
                encoding=encoding,
            )
        )

    walk(parsed, "")
    return parts


def attachment_metadata(parts: Iterable[BodyPart]) -> List[AttachmentMetadata]:
    result = []
    for part in parts:
        if part.is_attachment:
            result.append(
                AttachmentMetadata(
                    filename=part.filename,
                    content_type=part.content_type,
                    size=part.size,
                    content_id=part.content_id,
                )
            )
    return result


def decode_body_part(raw: bytes, part: BodyPart) -> str:
    payload = raw or b""
    if part.encoding == "base64":
        import base64

        payload = base64.b64decode(payload, validate=False)
    elif part.encoding == "quoted-printable":
        import quopri

        payload = quopri.decodestring(payload)
    charset = part.charset or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def parse_headers(raw_header: bytes) -> Message:
    return email.message_from_bytes(raw_header or b"")


def build_email_content(
    email_id: str,
    raw_header: bytes,
    parts: List[BodyPart],
    plain_text: str,
    html_text: str,
    include_body: bool,
    include_attachment_metadata: bool,
) -> EmailContent:
    headers = parse_headers(raw_header)
    subject = decode_mime(headers.get("Subject")) or "(no subject)"
    plain_clean, plain_removed = strip_probable_quotes(plain_text)
    html_converted = html_to_text(html_text)
    html_clean, html_removed = strip_probable_quotes(html_converted)
    body = plain_clean or html_clean
    attachments = attachment_metadata(parts) if include_attachment_metadata else []
    raw_headers = {
        "Message-ID": headers.get("Message-ID"),
        "In-Reply-To": headers.get("In-Reply-To"),
        "References": headers.get("References"),
        "Subject": subject,
        "Date": headers.get("Date"),
    }

    warnings = []
    if attachments:
        warnings.append("邮件包含附件；第一版只读取附件元信息，未分析附件内容。")

    return EmailContent(
        email_id=email_id,
        message_id=(headers.get("Message-ID") or "").strip() or None,
        in_reply_to=(headers.get("In-Reply-To") or "").strip() or None,
        references=parse_message_ids(headers.get("References")),
        subject=subject,
        from_=", ".join(parse_address_list(headers.get("From"))),
        to=parse_address_list(headers.get("To")),
        cc=parse_address_list(headers.get("Cc")),
        bcc=parse_address_list(headers.get("Bcc")),
        date=parse_date(headers.get("Date")),
        plain_text=body if include_body and plain_clean else "",
        html_text_converted_to_text=html_clean if include_body and not plain_clean else "",
        snippet=text_to_snippet(body),
        attachments=attachments,
        raw_headers=raw_headers,
        quoted_text_removed="true"
        if plain_removed == "true" or html_removed == "true"
        else "unknown",
        warnings=warnings,
    )


def build_search_result(
    email_id: str,
    raw_header: bytes,
    parts: List[BodyPart],
    snippet_source: str,
) -> EmailSearchResult:
    headers = parse_headers(raw_header)
    attachments = attachment_metadata(parts)
    return EmailSearchResult(
        email_id=email_id,
        message_id=(headers.get("Message-ID") or "").strip() or None,
        subject=decode_mime(headers.get("Subject")) or "(no subject)",
        from_=", ".join(parse_address_list(headers.get("From"))),
        to=parse_address_list(headers.get("To")),
        cc=parse_address_list(headers.get("Cc")),
        date=parse_date(headers.get("Date")),
        snippet=text_to_snippet(snippet_source),
        has_attachments=bool(attachments),
        attachment_count=len(attachments),
    )
