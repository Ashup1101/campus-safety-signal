"""Retrieval over the real-only incidents with DuckDB full-text search (BM25).

Documents are built from structured fields (type, place, date, outcome), never from article
text, and sensitive incidents are never indexed. The index lives in data/rag/index.duckdb and is
rebuilt from the warehouse after `make transform`; a query is a plain string plus optional
date and place filters that are applied in SQL, not by the model.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from campus_safety.patterns.categories import category

INDEX = Path("data", "rag", "index.duckdb")
DUCKDB_CONFIG: dict[str, str | bool | int | float | list[str]] = {
    "memory_limit": "1GB",
    "threads": 2,
}
SOURCE_SQL = (
    "select incident_id, source, source_ref, incident_type, severity_tier, location_text,"
    " date_reported, occurred_from, disposition, summary, count"
    " from gold.incidents_real where not is_sensitive"
)
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Document:
    doc_id: str  # incident_id
    source: str
    source_ref: str
    text: str
    day: date | None
    place: str | None
    kind: str

    @property
    def citation(self) -> str:
        when = self.day.isoformat() if self.day else "date unknown"
        return f"{self.doc_id[:12]} ({self.source}, {when})"


@dataclass(frozen=True)
class Hit:
    doc: Document
    score: float


def document_text(
    incident_type: str | None,
    location: str | None,
    day: date | None,
    disposition: str | None,
    summary: str | None,
    count: int | None,
) -> str:
    """One readable line per incident from fields only."""
    kind = category(incident_type or "")
    parts = [kind[0].upper() + kind[1:]]
    if incident_type:
        parts.append(f"({incident_type.lower()})")
    if count and count > 1:
        parts.append(f"x{count}")
    if location:
        parts.append(f"at {location}")
    if day:
        parts.append(f"on {day.strftime('%A %B %-d, %Y')}")
    if disposition:
        parts.append(f"; outcome: {disposition.lower()}")
    if summary and not incident_type:
        parts.append(summary)
    return " ".join(parts)


def build(warehouse: Path, index: Path = INDEX) -> int:
    """Rebuild the index from the warehouse; returns the document count."""
    if not warehouse.exists():
        raise FileNotFoundError(f"no warehouse at {warehouse}; run make transform first")
    index.parent.mkdir(parents=True, exist_ok=True)
    if index.exists():
        index.unlink()
    with duckdb.connect(str(warehouse), read_only=True, config=DUCKDB_CONFIG) as source:
        rows = source.execute(SOURCE_SQL).fetchall()
    docs = [
        (
            iid,
            src,
            ref,
            document_text(kind, place, day, disposition, summary, count),
            day,
            place,
            category(kind or ""),
        )
        for iid, src, ref, kind, _tier, place, day, _at, disposition, summary, count in rows
    ]
    with duckdb.connect(str(index), config=DUCKDB_CONFIG) as con:
        con.execute("INSTALL fts; LOAD fts")
        con.execute(
            "CREATE TABLE docs (doc_id VARCHAR PRIMARY KEY, source VARCHAR, source_ref VARCHAR,"
            " text VARCHAR, day DATE, place VARCHAR, kind VARCHAR)"
        )
        if docs:
            con.executemany("INSERT INTO docs VALUES (?, ?, ?, ?, ?, ?, ?)", docs)
        con.execute("PRAGMA create_fts_index('docs', 'doc_id', 'text', 'place', 'kind')")
    return len(docs)


class Index:
    def __init__(self, path: Path = INDEX) -> None:
        if not path.exists():
            raise FileNotFoundError(f"no index at {path}; run rag build first")
        self.con = duckdb.connect(str(path), read_only=True, config=DUCKDB_CONFIG)
        self.con.execute("LOAD fts")

    def close(self) -> None:
        self.con.close()

    def search(
        self,
        query: str,
        k: int = 8,
        since: date | None = None,
        until: date | None = None,
        place: str | None = None,
    ) -> list[Hit]:
        terms = " ".join(_TOKEN.findall(query.lower()))
        if not terms:
            return []
        rows = self.con.execute(
            "select doc_id, source, source_ref, text, day, place, kind, score from ("
            " select *, fts_main_docs.match_bm25(doc_id, $q) as score from docs)"
            " where score is not null"
            " and ($since is null or day >= $since) and ($until is null or day <= $until)"
            " and ($place is null or contains(lower(place), lower($place)))"
            " order by score desc, day desc limit $k",
            {"q": terms, "since": since, "until": until, "place": place, "k": k},
        ).fetchall()
        return [
            Hit(Document(iid, src, ref, text, day, where, kind), float(score))
            for iid, src, ref, text, day, where, kind, score in rows
        ]

    def count(self) -> int:
        row = self.con.execute("select count(*) from docs").fetchone()
        return int(row[0]) if row else 0
