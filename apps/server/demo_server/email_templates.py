"""Email texts: the message's own words, then the same short footer on every email. Plain text
first; a small HTML copy with the same words. No images, no tracking pixels, no click tracking."""

import html
import os

WEB = os.environ.get("DEMO_WEB_URL", "http://localhost:3100")


def footer(web: str = WEB) -> str:
    return (
        "Campus Safety Signal. Not an official IU service. Built from public data.\n"
        f"Privacy policy: {web}/privacy\n"
        f"Terms: {web}/terms"
    )


def text(body: str, web: str = WEB) -> str:
    return f"{body.rstrip()}\n\n--\n{footer(web)}\n"


def html_copy(subject: str, body: str, web: str = WEB) -> str:
    """The same words as the plain text, with links clickable; nothing loads from the web."""

    def paragraphs(words: str) -> str:
        lines = [html.escape(line) for line in words.strip().split("\n")]
        linked = [_link(line) for line in lines]
        return "".join(f"<p>{line}</p>" if line else "" for line in linked)

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(subject)}</title></head>"
        '<body style="font-family: system-ui, sans-serif; line-height: 1.5; max-width: 36em">'
        f"{paragraphs(body)}<hr>"
        f'<div style="font-size: 0.85em; color: #555">{paragraphs(footer(web))}</div>'
        "</body></html>"
    )


def _link(line: str) -> str:
    words = []
    for word in line.split(" "):
        if word.startswith(("https://", "http://")):
            word = f'<a href="{word}">{word}</a>'
        words.append(word)
    return " ".join(words)
