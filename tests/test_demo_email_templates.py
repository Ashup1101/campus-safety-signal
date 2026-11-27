"""Email texts: fixed footer, plain text first, a small HTML copy with no images or tracking."""

from demo_server import email_templates

WEB = "https://web.example.test"
BODY = "You asked for morning digests. Confirm here: https://x.test/c/abc\nIf not you, do nothing."


def test_plain_text_snapshot() -> None:
    assert email_templates.text(BODY, WEB) == (
        "You asked for morning digests. Confirm here: https://x.test/c/abc\n"
        "If not you, do nothing.\n"
        "\n--\n"
        "Campus Safety Signal. Not an official IU service. Built from public data.\n"
        "Privacy policy: https://web.example.test/privacy\n"
        "Terms: https://web.example.test/terms\n"
    )


def test_html_copy_snapshot_has_no_images_or_tracking() -> None:
    found = email_templates.html_copy("Confirm <digests>", BODY, WEB)
    assert found == (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>Confirm &lt;digests&gt;</title></head>"
        '<body style="font-family: system-ui, sans-serif; line-height: 1.5; max-width: 36em">'
        '<p>You asked for morning digests. Confirm here: <a href="https://x.test/c/abc">'
        "https://x.test/c/abc</a></p><p>If not you, do nothing.</p><hr>"
        '<div style="font-size: 0.85em; color: #555">'
        "<p>Campus Safety Signal. Not an official IU service. Built from public data.</p>"
        '<p>Privacy policy: <a href="https://web.example.test/privacy">'
        "https://web.example.test/privacy</a></p>"
        '<p>Terms: <a href="https://web.example.test/terms">https://web.example.test/terms</a></p>'
        "</div></body></html>"
    )
    assert "<img" not in found and "pixel" not in found and "utm_" not in found


def test_html_escapes_the_message_words() -> None:
    found = email_templates.html_copy("s", '<script>alert("x")</script>', WEB)
    assert "<script>" not in found and "&lt;script&gt;" in found


def test_every_sent_email_has_the_footer_in_both_parts() -> None:
    from email.message import EmailMessage

    from demo_server.email_channel import EmailChannel, EmailSettings

    channel = EmailChannel.__new__(EmailChannel)
    channel.settings = EmailSettings(sender="a@example.test")
    row = {
        "to_address": "p@example.test",
        "subject": "Hi",
        "body": "Hello",
        "unsubscribe_url": None,
    }
    message: EmailMessage = channel.message(row)
    plain = message.get_body(("plain",))
    rich = message.get_body(("html",))
    assert plain is not None and rich is not None
    for part in (plain, rich):
        assert "Not an official IU service" in part.get_content()
