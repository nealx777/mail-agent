from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import configure_logging, load_settings
from .imap_client import NeteaseMailClient
from .reply_tasks import load_extract_prompt
from .reply_status import get_inbox_reply_status
from .thread_builder import get_full_thread


def _json_print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _client() -> NeteaseMailClient:
    settings = load_settings()
    configure_logging(settings.log_level)
    return NeteaseMailClient(settings)


def cmd_test_connection(args) -> None:
    with _client() as client:
        _json_print(client.test_connection(mailbox=args.mailbox))


def cmd_list_mailboxes(args) -> None:
    with _client() as client:
        _json_print([item.to_dict() for item in client.list_mailboxes()])


def cmd_search(args) -> None:
    with _client() as client:
        results = client.search_email(
            query=args.query,
            from_email=args.from_email,
            subject=args.subject,
            since=args.since,
            before=args.before,
            mailbox=args.mailbox,
            limit=args.limit,
        )
        _json_print([item.to_dict() for item in results])


def cmd_read(args) -> None:
    with _client() as client:
        content = client.read_email(
            args.email_id,
            mailbox=args.mailbox,
            include_body=not args.no_body,
            include_attachment_metadata=not args.no_attachment_metadata,
        )
        _json_print(content.to_dict())


def cmd_thread(args) -> None:
    with _client() as client:
        thread = get_full_thread(
            client,
            args.email_id,
            mailbox=args.mailbox,
            lookback_days=args.lookback_days,
            include_attachment_metadata=not args.no_attachment_metadata,
        ).to_dict()
    if args.output:
        Path(args.output).write_text(json.dumps(thread, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入：{args.output}")
    else:
        _json_print(thread)


def cmd_reply_status(args) -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    with NeteaseMailClient(settings) as client:
        report = get_inbox_reply_status(
            client,
            inbox_mailbox=args.inbox_mailbox or settings.inbox_mailbox,
            sent_mailbox=args.sent_mailbox or settings.sent_mailbox,
            since=args.since,
            before=args.before,
            sent_since=args.sent_since,
            sent_before=args.sent_before,
            query=args.query,
            from_email=args.from_email,
            subject=args.subject,
            limit=args.limit,
            sent_scan_limit=args.sent_scan_limit,
        ).to_dict()
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入：{args.output}")
    else:
        _json_print(report)


def cmd_print_prompt(args) -> None:
    print(load_extract_prompt())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mail-agent",
        description="mail agent 只读 MCP Server 调试 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    test = subparsers.add_parser("test-connection", help="测试 IMAP 只读连接")
    test.add_argument("--mailbox", default="INBOX")
    test.set_defaults(func=cmd_test_connection)

    mailboxes = subparsers.add_parser("list-mailboxes", help="列出邮箱目录和可用于读取的 select_name")
    mailboxes.set_defaults(func=cmd_list_mailboxes)

    search = subparsers.add_parser("search", help="搜索邮件")
    search.add_argument("--query")
    search.add_argument("--from", dest="from_email")
    search.add_argument("--subject")
    search.add_argument("--since", help="YYYY-MM-DD")
    search.add_argument("--before", help="YYYY-MM-DD")
    search.add_argument("--mailbox", default="INBOX")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(func=cmd_search)

    read = subparsers.add_parser("read", help="读取单封邮件")
    read.add_argument("--email-id", required=True)
    read.add_argument("--mailbox", default="INBOX")
    read.add_argument("--no-body", action="store_true")
    read.add_argument("--no-attachment-metadata", action="store_true")
    read.set_defaults(func=cmd_read)

    thread = subparsers.add_parser("thread", help="拉取完整邮件线程")
    thread.add_argument("--email-id", required=True)
    thread.add_argument("--mailbox", default="INBOX")
    thread.add_argument("--lookback-days", type=int, default=90)
    thread.add_argument("--no-attachment-metadata", action="store_true")
    thread.add_argument("--output")
    thread.set_defaults(func=cmd_thread)

    reply_status = subparsers.add_parser("reply-status", help="判断收件箱邮件是否已在已发送目录中回复")
    reply_status.add_argument("--inbox-mailbox", help="收件箱目录；默认读取 NETEASE_INBOX_MAILBOX 或 INBOX")
    reply_status.add_argument("--sent-mailbox", help="已发送目录；默认读取 NETEASE_SENT_MAILBOX 或 Sent")
    reply_status.add_argument("--query")
    reply_status.add_argument("--from", dest="from_email")
    reply_status.add_argument("--subject")
    reply_status.add_argument("--since", help="只筛选这个日期后的收件箱邮件，格式 YYYY-MM-DD")
    reply_status.add_argument("--before", help="只筛选这个日期前的收件箱邮件，格式 YYYY-MM-DD")
    reply_status.add_argument("--sent-since", help="已发送目录扫描起始日期；默认从最早收件箱邮件前一天开始")
    reply_status.add_argument("--sent-before", help="已发送目录扫描截止日期，格式 YYYY-MM-DD")
    reply_status.add_argument("--limit", type=int, default=50)
    reply_status.add_argument("--sent-scan-limit", type=int, default=1000)
    reply_status.add_argument("--output")
    reply_status.set_defaults(func=cmd_reply_status)

    prompt = subparsers.add_parser("print-prompt", help="输出固定邮件需求拆解 prompt")
    prompt.set_defaults(func=cmd_print_prompt)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
