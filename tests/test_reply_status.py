from __future__ import annotations

from netease_mail_mcp.imap_client import _mailbox_arg, _parse_list_mailbox
from netease_mail_mcp.reply_status import get_inbox_reply_status
from netease_mail_mcp.schemas import EmailContent, EmailSearchResult


class FakeReplyStatusClient:
    def __init__(self, inbox_messages, sent_messages):
        self.inbox_messages = {message.email_id: message for message in inbox_messages}
        self.sent_messages = {message.email_id: message for message in sent_messages}

    def search_email(
        self,
        query=None,
        from_email=None,
        subject=None,
        since=None,
        before=None,
        mailbox="INBOX",
        limit=20,
    ):
        return [
            EmailSearchResult(
                email_id=message.email_id,
                message_id=message.message_id,
                subject=message.subject,
                from_=message.from_,
                to=message.to,
                cc=message.cc,
                date=message.date,
                snippet="",
                has_attachments=False,
                attachment_count=0,
            )
            for message in self.inbox_messages.values()
        ][:limit]

    def read_email(
        self,
        email_id,
        mailbox="INBOX",
        include_body=True,
        include_attachment_metadata=True,
    ):
        if mailbox == "Sent":
            return self.sent_messages[email_id]
        return self.inbox_messages[email_id]

    def candidate_uids(self, mailbox, since, before=None, max_count=500):
        return list(self.sent_messages.keys())[:max_count]


def test_parse_list_mailbox_decodes_sent_role() -> None:
    mailbox = _parse_list_mailbox(b'(\\HasNoChildren \\Sent) "/" "&XfJT0ZAB-"')

    assert mailbox is not None
    assert mailbox.name == "已发送"
    assert mailbox.select_name == "&XfJT0ZAB-"
    assert mailbox.role == "sent"


def test_mailbox_arg_quotes_names_with_spaces() -> None:
    assert _mailbox_arg("Sent Messages") == '"Sent Messages"'
    assert _mailbox_arg("INBOX") == "INBOX"


def test_reply_status_counts_direct_header_replies() -> None:
    inbox = _email(
        email_id="101",
        message_id="<inbox-101@example.com>",
        subject="Project update",
        from_="Customer <customer@example.com>",
        to=["Support <support@example.com>"],
        date="Mon, 01 Jan 2024 10:00:00 +0800",
    )
    sent = _email(
        email_id="201",
        message_id="<sent-201@example.com>",
        in_reply_to="<inbox-101@example.com>",
        references=["<inbox-101@example.com>"],
        subject="Re: Project update",
        from_="Support <support@example.com>",
        to=["Customer <customer@example.com>"],
        date="Mon, 01 Jan 2024 11:00:00 +0800",
    )
    client = FakeReplyStatusClient([inbox], [sent])

    report = get_inbox_reply_status(client, sent_mailbox="Sent")

    assert report.checked_count == 1
    assert report.replied_count == 1
    assert report.items[0].reply_count == 1
    assert report.items[0].replies[0].match_method == "direct_in_reply_to"


def test_reply_status_falls_back_to_subject_recipient_time() -> None:
    inbox = _email(
        email_id="102",
        message_id=None,
        subject="CES sample schedule",
        from_="customer@example.com",
        to=["neal@example.com"],
        date="Mon, 01 Jan 2024 10:00:00 +0800",
    )
    sent = _email(
        email_id="202",
        message_id="<sent-202@example.com>",
        subject="Re: CES sample schedule",
        from_="neal@example.com",
        to=["customer@example.com"],
        date="Mon, 01 Jan 2024 12:00:00 +0800",
    )
    client = FakeReplyStatusClient([inbox], [sent])

    report = get_inbox_reply_status(client, sent_mailbox="Sent")

    assert report.items[0].replied is True
    assert report.items[0].reply_count == 1
    assert report.items[0].replies[0].match_method == "fallback_subject_recipient_time"
    assert any("人工复核" in warning for warning in report.items[0].warnings)


def _email(
    email_id,
    message_id,
    subject,
    from_,
    to,
    date,
    in_reply_to=None,
    references=None,
):
    return EmailContent(
        email_id=email_id,
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references or [],
        subject=subject,
        from_=from_,
        to=to,
        cc=[],
        bcc=[],
        date=date,
        plain_text="",
        html_text_converted_to_text="",
        snippet="",
    )
