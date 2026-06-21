from __future__ import annotations

from pathlib import Path

from netease_mail_mcp.email_parser import (
    build_email_content,
    decode_body_part,
    html_to_text,
    normalize_subject,
    parse_bodystructure,
    strip_probable_quotes,
)


def test_normalize_subject_removes_reply_prefixes() -> None:
    assert normalize_subject("回复: Re: Fwd: CES sample schedule") == "ces sample schedule"


def test_html_to_text_is_readable() -> None:
    text = html_to_text("<html><body><p>Hello<br>World</p><script>x</script></body></html>")
    assert "Hello" in text
    assert "World" in text
    assert "script" not in text


def test_strip_probable_quotes_keeps_new_content() -> None:
    cleaned, removed = strip_probable_quotes("Please confirm delivery.\n\n> old content")
    assert cleaned == "Please confirm delivery."
    assert removed == "true"


def test_parse_bodystructure_extracts_text_and_attachment_metadata() -> None:
    raw = (
        b'(("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "QUOTED-PRINTABLE" 120 5 NIL NIL NIL NIL)'
        b'("APPLICATION" "PDF" ("NAME" "specification.pdf") NIL NIL "BASE64" 204800 NIL '
        b'("ATTACHMENT" ("FILENAME" "specification.pdf")) NIL NIL) "MIXED" NIL NIL NIL)'
    )
    parts = parse_bodystructure(raw)
    assert parts[0].part_number == "1"
    assert parts[0].content_type == "text/plain"
    assert parts[0].charset == "utf-8"
    assert parts[1].part_number == "2"
    assert parts[1].filename == "specification.pdf"
    assert parts[1].size == 204800


def test_build_email_content_from_fixture_header() -> None:
    raw = Path("tests/fixtures/sample_email.eml").read_bytes()
    header = raw.split(b"\n\n", 1)[0]
    bodystructure = (
        b'(("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "QUOTED-PRINTABLE" 120 5 NIL NIL NIL NIL)'
        b'("APPLICATION" "PDF" ("NAME" "specification.pdf") NIL NIL "BASE64" 204800 NIL '
        b'("ATTACHMENT" ("FILENAME" "specification.pdf")) NIL NIL) "MIXED" NIL NIL NIL)'
    )
    parts = parse_bodystructure(bodystructure)
    content = build_email_content(
        email_id="101",
        raw_header=header,
        parts=parts,
        plain_text="Could you confirm the sample delivery date?\n\n> old content",
        html_text="",
        include_body=True,
        include_attachment_metadata=True,
    )
    assert content.message_id == "<sample-001@example.com>"
    assert content.subject == "Re: CES sample schedule"
    assert content.attachments[0].filename == "specification.pdf"
    assert "sample delivery date" in content.plain_text
