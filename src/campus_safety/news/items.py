"""Items (headline, link, short summary, time) from the Phase 2a bronze pages.

Feeds and listing pages only: titles and feed summaries are the whole input, article pages are
never fetched or stored. Every body is untrusted: XML goes through defusedxml, HTML through the
stdlib parser, and nothing in a page is ever executed or followed.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser

from defusedxml import ElementTree

from campus_safety.collectors.sources import BY_NAME
from campus_safety.events import LOCAL
from campus_safety.lake.bronze import Manifest

MAX_TEXT = 2_000  # characters kept per field


@dataclass(frozen=True)
class RawItem:
    title: str
    url: str
    summary: str = ""
    published_at: datetime | None = None  # UTC


@dataclass(frozen=True)
class Item:
    source: str  # bronze source name (the outlet)
    tier: int
    item_id: str  # sha256(source|url)[:16]
    url: str
    title: str
    summary: str
    published_at: datetime | None  # UTC
    source_ref: str  # bronze key of the page that listed it
    run_id: str
    observed_at: datetime  # UTC fetch time of that page

    @property
    def text(self) -> str:
        return f"{self.title}. {self.summary}".strip() if self.summary else self.title


class ItemsLayoutError(ValueError):
    pass


class _Text(HTMLParser):
    """Visible text of an HTML fragment (feed summaries carry markup)."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def text_of(fragment: str) -> str:
    parser = _Text()
    parser.feed(unescape(fragment))
    return _squeeze(" ".join(parser.parts))


def _squeeze(text: str) -> str:
    return " ".join(text.split())[:MAX_TEXT]


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if len(value) == 10:  # a bare date (sitemap lastmod) is the outlet's local day
            at = at.replace(tzinfo=LOCAL)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at.astimezone(UTC)


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


def parse_rss(body: bytes) -> list[RawItem]:
    """RSS 2.0 <item> entries (title, link, description, pubDate)."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as e:
        raise ItemsLayoutError("feed is not well-formed XML") from e
    found = []
    for node in root.iter():
        if _local(node.tag) != "item":
            continue
        fields = {_local(child.tag): (child.text or "") for child in node}
        url = fields.get("link", "").strip()
        title = text_of(fields.get("title", ""))
        if url.startswith("https://") and title:
            found.append(
                RawItem(
                    title, url, text_of(fields.get("description", "")), _when(fields.get("pubDate"))
                )
            )
    return found


def parse_sitemap(body: bytes) -> list[RawItem]:
    """Sitemap <url> entries; the headline is read from the article slug."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as e:
        raise ItemsLayoutError("sitemap is not well-formed XML") from e
    found = []
    for node in root.iter():
        if _local(node.tag) != "url":
            continue
        fields = {_local(child.tag): (child.text or "") for child in node}
        url = fields.get("loc", "").strip()
        slug = url.rstrip("/").rpartition("/")[2]
        title = _squeeze(re.sub(r"[-_]+", " ", slug))
        if url.startswith("https://") and title:
            found.append(RawItem(title, url, "", _when(fields.get("lastmod"))))
    return found


class _CityNews(HTMLParser):
    """bloomington.in.gov/news: <a href="/news/..."><article>... <h3><span>title</span></h3>
    <time datetime="..."> <p>summary</p></article></a>."""

    BASE = "https://bloomington.in.gov"

    def __init__(self) -> None:
        super().__init__()
        self.items: list[RawItem] = []
        self._href: str | None = None
        self._field: str | None = None
        self._fields: dict[str, list[str]] = {}
        self._when: str | None = None
        self._h3 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "a" and (a.get("href") or "").startswith("/news/"):
            self._href, self._fields, self._when = a["href"] or "", {}, None
        elif self._href is None:
            return
        elif tag == "h3":
            self._h3 = True
        elif tag == "span" and self._h3:
            self._field = "title"
        elif tag == "time":
            self._when = a.get("datetime")
        elif tag == "p":
            self._field = "summary"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("span", "p"):
            self._field = None
        elif tag == "h3":
            self._h3 = False
        elif tag == "a" and self._href is not None:
            title = _squeeze(" ".join(self._fields.get("title", [])))
            if title:
                summary = _squeeze(" ".join(self._fields.get("summary", [])))
                self.items.append(
                    RawItem(title, self.BASE + self._href, summary, _when(self._when))
                )
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None and self._field:
            self._fields.setdefault(self._field, []).append(data)


def parse_city_news(body: bytes) -> list[RawItem]:
    parser = _CityNews()
    parser.feed(body.decode("utf-8", errors="replace"))
    return parser.items


class _Notices(HTMLParser):
    """protect.iu.edu crime notices: the Bloomington accordion section, as links or plain text."""

    SECTION = "sectbloomington"
    BASE = "https://protect.iu.edu"

    def __init__(self) -> None:
        super().__init__()
        self.found = False
        self.links: list[tuple[str, list[str]]] = []
        self.text: list[str] = []
        self._depth = 0
        self._in_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "div" and a.get("id") == self.SECTION:
            self.found, self._depth = True, 1
            return
        if not self._depth:
            return
        if tag == "div":
            self._depth += 1
        elif tag == "a" and a.get("href"):
            href = a["href"] or ""
            self.links.append((href if href.startswith("https://") else self.BASE + href, []))
            self._in_link = True

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag == "div":
            self._depth -= 1
        elif tag == "a":
            self._in_link = False

    def handle_data(self, data: str) -> None:
        if not self._depth:
            return
        self.text.append(data)
        if self._in_link and self.links:
            self.links[-1][1].append(data)


def parse_iu_notices(body: bytes) -> list[RawItem]:
    parser = _Notices()
    parser.feed(body.decode("utf-8", errors="replace"))
    if not parser.found:
        raise ItemsLayoutError("notices page has no Bloomington section")
    text = _squeeze(" ".join(parser.text))
    if not text or text.lower().startswith("no active crime notices"):
        return []
    items = [RawItem(_squeeze(" ".join(parts)), url, text) for url, parts in parser.links if parts]
    return items or [RawItem(text[:160], BY_NAME["iu_crime_notices"].url, text)]


PARSERS: dict[str, Callable[[bytes], list[RawItem]]] = {
    "iu_crime_notices": parse_iu_notices,
    "city_news_releases": parse_city_news,
    "news_bloomingtonian": parse_rss,
    "news_b_square_bulletin": parse_rss,
    "news_ids": parse_sitemap,
    "news_ipm": parse_rss,
}


def item_id(source: str, url: str) -> str:
    return hashlib.sha256(f"{source}|{url}".encode()).hexdigest()[:16]


def items(manifest: Manifest, body: bytes) -> list[Item]:
    """The items one bronze page lists, one per URL (a page may repeat a link)."""
    parse = PARSERS.get(manifest.source)
    if parse is None:
        raise ItemsLayoutError(f"no item parser for source {manifest.source}")
    tier = BY_NAME[manifest.source].tier
    seen: dict[str, Item] = {}
    for raw in parse(body):
        seen.setdefault(
            raw.url,
            Item(
                manifest.source,
                tier,
                item_id(manifest.source, raw.url),
                raw.url,
                raw.title,
                raw.summary,
                raw.published_at,
                manifest.key,
                manifest.run_id,
                manifest.fetched_at.astimezone(UTC),
            ),
        )
    return list(seen.values())
