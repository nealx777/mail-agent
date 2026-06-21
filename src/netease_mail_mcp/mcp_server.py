from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict, Optional

from .config import configure_logging, load_settings
from .imap_client import NeteaseMailClient
from .reply_tasks import build_extract_reply_tasks_payload
from .reply_status import get_inbox_reply_status
from .thread_builder import get_full_thread as build_full_thread

SERVER_NAME = "netease-mail-mcp"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOL_VERSIONS = {"2025-06-18", "2025-03-26", "2024-11-05"}


def _settings():
    settings = load_settings()
    configure_logging(settings.log_level)
    return settings


def _search_email(arguments: Dict[str, Any]) -> list[dict[str, Any]]:
    with NeteaseMailClient(_settings()) as client:
        results = client.search_email(
            query=arguments.get("query"),
            from_email=arguments.get("from_email"),
            subject=arguments.get("subject"),
            since=arguments.get("since"),
            before=arguments.get("before"),
            mailbox=arguments.get("mailbox", "INBOX"),
            limit=int(arguments.get("limit", 20)),
        )
        return [item.to_dict() for item in results]


def _list_mailboxes(arguments: Dict[str, Any]) -> list[dict[str, Any]]:
    with NeteaseMailClient(_settings()) as client:
        return [item.to_dict() for item in client.list_mailboxes()]


def _read_email(arguments: Dict[str, Any]) -> dict[str, Any]:
    email_id = arguments.get("email_id")
    if not email_id:
        raise ValueError("email_id 是必填参数。")
    with NeteaseMailClient(_settings()) as client:
        return client.read_email(
            email_id=str(email_id),
            mailbox=arguments.get("mailbox", "INBOX"),
            include_body=bool(arguments.get("include_body", True)),
            include_attachment_metadata=bool(
                arguments.get("include_attachment_metadata", True)
            ),
        ).to_dict()


def _get_full_thread(arguments: Dict[str, Any]) -> dict[str, Any]:
    email_id = arguments.get("email_id")
    if not email_id:
        raise ValueError("email_id 是必填参数。")
    with NeteaseMailClient(_settings()) as client:
        return build_full_thread(
            client,
            email_id=str(email_id),
            mailbox=arguments.get("mailbox", "INBOX"),
            lookback_days=int(arguments.get("lookback_days", 90)),
            include_attachment_metadata=bool(
                arguments.get("include_attachment_metadata", True)
            ),
        ).to_dict()


def _extract_reply_tasks(arguments: Dict[str, Any]) -> dict[str, Any]:
    thread_json = arguments.get("thread_json")
    if not isinstance(thread_json, dict):
        raise ValueError("thread_json 必须是 object。")
    return build_extract_reply_tasks_payload(
        thread_json,
        output_language=arguments.get("output_language", "zh-CN"),
    )


def _get_inbox_reply_status(arguments: Dict[str, Any]) -> dict[str, Any]:
    settings = _settings()
    with NeteaseMailClient(settings) as client:
        return get_inbox_reply_status(
            client,
            inbox_mailbox=arguments.get("inbox_mailbox", settings.inbox_mailbox),
            sent_mailbox=arguments.get("sent_mailbox", settings.sent_mailbox),
            since=arguments.get("since"),
            before=arguments.get("before"),
            sent_since=arguments.get("sent_since"),
            sent_before=arguments.get("sent_before"),
            query=arguments.get("query"),
            from_email=arguments.get("from_email"),
            subject=arguments.get("subject"),
            limit=int(arguments.get("limit", 50)),
            sent_scan_limit=int(arguments.get("sent_scan_limit", 1000)),
        ).to_dict()


TOOL_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "list_mailboxes": _list_mailboxes,
    "search_email": _search_email,
    "read_email": _read_email,
    "get_full_thread": _get_full_thread,
    "get_inbox_reply_status": _get_inbox_reply_status,
    "extract_reply_tasks": _extract_reply_tasks,
}


TOOLS = [
    {
        "name": "list_mailboxes",
        "description": "列出邮箱目录，返回展示名和可用于其他工具 mailbox 参数的 select_name。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "search_email",
        "description": "按关键词、发件人、主题、日期范围搜索邮件；默认不返回完整正文。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "from_email": {"type": "string"},
                "subject": {"type": "string"},
                "since": {"type": "string", "description": "YYYY-MM-DD"},
                "before": {"type": "string", "description": "YYYY-MM-DD"},
                "mailbox": {"type": "string", "default": "INBOX"},
                "limit": {"type": "number", "default": 20},
            },
        },
    },
    {
        "name": "read_email",
        "description": "读取单封邮件的结构化内容；附件只返回元信息。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "mailbox": {"type": "string", "default": "INBOX"},
                "include_body": {"type": "boolean", "default": True},
                "include_attachment_metadata": {"type": "boolean", "default": True},
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "get_full_thread",
        "description": "根据一封邮件尽量重建完整邮件线程，并按时间升序返回稳定 JSON。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "mailbox": {"type": "string", "default": "INBOX"},
                "lookback_days": {"type": "number", "default": 90},
                "include_attachment_metadata": {"type": "boolean", "default": True},
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "get_inbox_reply_status",
        "description": "读取收件箱和已发送目录，判断收件箱邮件是否已回复以及回复次数。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "inbox_mailbox": {"type": "string", "default": "INBOX"},
                "sent_mailbox": {"type": "string", "default": "Sent"},
                "query": {"type": "string"},
                "from_email": {"type": "string"},
                "subject": {"type": "string"},
                "since": {"type": "string", "description": "筛选收件箱邮件的起始日期，YYYY-MM-DD"},
                "before": {"type": "string", "description": "筛选收件箱邮件的截止日期，YYYY-MM-DD"},
                "sent_since": {"type": "string", "description": "扫描已发送目录的起始日期，YYYY-MM-DD"},
                "sent_before": {"type": "string", "description": "扫描已发送目录的截止日期，YYYY-MM-DD"},
                "limit": {"type": "number", "default": 50},
                "sent_scan_limit": {"type": "number", "default": 1000},
            },
        },
    },
    {
        "name": "extract_reply_tasks",
        "description": "返回固定分析 prompt 和结构化输出要求；第一版不在 MCP 内部调用外部 LLM。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thread_json": {"type": "object"},
                "output_language": {"type": "string", "default": "zh-CN"},
            },
            "required": ["thread_json"],
        },
    },
]


def _response(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _tool_result(value: Any, is_error: bool = False) -> Dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": value if isinstance(value, dict) else {"result": value},
        "isError": is_error,
    }


def handle_message(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    # JSON-RPC notification 没有 id，不需要响应。
    if request_id is None and method and method.startswith("notifications/"):
        return None

    if method == "initialize":
        requested_version = params.get("protocolVersion")
        protocol_version = (
            requested_version
            if requested_version in SUPPORTED_PROTOCOL_VERSIONS
            else "2025-06-18"
        )
        return _response(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": "网易企业邮箱只读 MCP Server：只搜索、读取和重建邮件线程，不发送、不删除、不移动、不标记邮件。",
            },
        )

    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return _error(request_id, -32602, f"Unknown tool: {name}")
        try:
            return _response(request_id, _tool_result(handler(arguments)))
        except Exception as exc:
            return _response(request_id, _tool_result({"error": str(exc)}, is_error=True))

    if method == "ping":
        return _response(request_id, {})

    return _error(request_id, -32601, f"Method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = handle_message(message)
        except Exception as exc:
            response = _error(None, -32700, f"Parse error: {exc}")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
