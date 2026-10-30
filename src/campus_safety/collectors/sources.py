"""The sources Phase 2a polls. Each response is stored raw in bronze; extraction is Phase 2b.

Feeds and listing pages only: article pages are not fetched (no republication, low load).
Delays follow each site's robots.txt crawl-delay where it sets one.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    name: str  # bronze source name
    url: str
    ext: str  # html | xml
    tier: int  # alerts.md: 1 official, 2 established local news
    delay: float  # seconds to wait after a request to this host


SOURCES = (
    Source(
        "iu_crime_notices",
        "https://protect.iu.edu/iu-police-department/campus-security-reports/crime-notices/notices.html",
        "html",
        1,
        2.0,
    ),
    Source("iu_emergency", "https://emergency.iu.edu/", "html", 1, 2.0),
    Source("city_news_releases", "https://bloomington.in.gov/news", "html", 1, 2.0),
    Source("news_bloomingtonian", "https://bloomingtonian.com/feed/", "xml", 2, 2.0),
    Source("news_b_square_bulletin", "https://bsquarebulletin.com/rss/", "xml", 2, 2.0),
    Source("news_ids", "https://www.idsnews.com/sitemap/recent.xml", "xml", 2, 10.0),
    Source("news_ipm", "https://www.ipm.org/news.rss", "xml", 2, 2.0),
)

BY_NAME = {source.name: source for source in SOURCES}
