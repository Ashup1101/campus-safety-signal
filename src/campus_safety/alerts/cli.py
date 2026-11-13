"""alerts: decide (dry run over the real-only incidents), publish (confirmed incidents not yet
published -> SNS, or a local fan-out when no topic is configured), sync-directory, report
(delivery counts and latency from the ledger). Logs carry counts only."""

import argparse
import logging
import os
import statistics
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from botocore.exceptions import BotoCoreError, ClientError

from campus_safety.alerts import directory, events, publish, snapshots
from campus_safety.alerts.ledger import LakeLedger, publish_key
from campus_safety.alerts.rules import Incident, decide
from campus_safety.lake.storage import LakeConfigError, open_lake

log = logging.getLogger("alerts")
WAREHOUSE = Path("data", "warehouse", "warehouse.duckdb")
TOPIC_VAR = "ALERTS_TOPIC_ARN"
DUCKDB_CONFIG: dict[str, str | bool | int | float | list[str]] = {
    "memory_limit": "1GB",
    "threads": 2,
}
# Zones are location texts until Phase 3 geocodes them; news clusters carry confirmed.
INCIDENTS_SQL = (
    "select i.incident_id, i.source, coalesce(n.confirmed, i.source = 'official'),"
    " i.severity_tier, i.incident_type, i.location_text, i.zone_id, i.occurred_from,"
    " i.is_sensitive, i.injuries"
    " from gold.incidents_real as i"
    " left join silver.news_incidents as n on n.cluster_id = i.source_record_id"
    " where i.date_reported >= $since"
)


def incidents(warehouse: Path, since: datetime) -> list[Incident]:
    if not warehouse.exists():
        raise LakeConfigError(f"no warehouse at {warehouse}; run make transform first")
    with duckdb.connect(str(warehouse), read_only=True, config=DUCKDB_CONFIG) as con:
        rows = con.execute(INCIDENTS_SQL, {"since": since.date()}).fetchall()
    found = []
    for iid, source, confirmed, tier, kind, location, zone, at, sensitive, injuries in rows:
        zones = tuple(z for z in (zone or location,) if z)
        found.append(
            Incident(
                iid,
                source,
                bool(confirmed),
                tier,
                kind or "",
                location,
                zones,
                at,
                bool(sensitive),
                injuries,
            )
        )
    return found


def dry_run(warehouse: Path, since: datetime) -> int:
    found = incidents(warehouse, since)
    routes = Counter(decide(i).route for i in found)
    reasons = Counter(decide(i).reason for i in found)
    log.info("%d incidents since %s: %s", len(found), since.date(), dict(sorted(routes.items())))
    for reason, n in reasons.most_common():
        log.info("  %5d  %s", n, reason)
    return 0


def publish_new(warehouse: Path, since: datetime) -> int:
    lake = open_lake(os.environ.get("LAKE_URI"))
    ledger = LakeLedger(lake)
    topic = os.environ.get(TOPIC_VAR)
    sns = None
    if topic:
        import boto3

        sns = boto3.client("sns")
    now = datetime.now(UTC)
    published = skipped = 0
    for incident in incidents(warehouse, since):
        decision = decide(incident)
        if decision.route != "alert":
            skipped += 1
            continue
        if not ledger.claim(publish_key(incident.incident_id, "alert"), now, incident.official_at):
            continue
        snapshots.store_incident(lake, incident)
        event = events.IncidentConfirmed(
            incident.incident_id,
            "alert",
            decision.severity,
            incident.zone_ids,
            incident.source,
            (incident.incident_id,),
            now,
            incident.official_at,
        )
        if sns is not None:
            publish.publish(sns, topic or "", event)
        else:
            lake.put(f"alerts/outbox/{incident.incident_id}/alert.json", event.to_json().encode())
        published += 1
    where = "SNS" if sns is not None else "the lake outbox (no ALERTS_TOPIC_ARN)"
    log.info("%d events published to %s, %d incidents not alertable", published, where, skipped)
    return 0


def sync_directory(path: Path) -> int:
    entries = directory.load(path)
    lake = open_lake(os.environ.get("LAKE_URI"))
    snapshots.store_directory(lake, entries)
    log.info(
        "%d subscribers synced (%d test accounts)",
        len(entries),
        sum(e.subscriber.test_account for e in entries),
    )
    return 0


def report() -> int:
    lake = open_lake(os.environ.get("LAKE_URI"))
    ledger = LakeLedger(lake)
    published = ledger.claims("published/")
    delivered = ledger.claims("delivered/")
    per_channel = Counter(key.rsplit("/", 1)[1] for key in delivered)
    latencies = []
    for key in delivered:
        import json

        entry = json.loads(lake.get(f"alerts/{key}"))
        if entry.get("official_at"):
            sent = datetime.fromisoformat(entry["at"])
            official = datetime.fromisoformat(entry["official_at"])
            latencies.append((sent - official).total_seconds())
    log.info(
        "%d incidents published, %d deliveries %s",
        len(published),
        len(delivered),
        dict(per_channel),
    )
    if latencies:
        log.info(
            "official -> delivered: median %.1f s, max %.1f s over %d deliveries",
            statistics.median(latencies),
            max(latencies),
            len(latencies),
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alerts", description=__doc__)
    parser.add_argument("--warehouse", type=Path, default=WAREHOUSE)
    parser.add_argument("--since", type=datetime.fromisoformat, default=None, help="YYYY-MM-DD")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("decide", help="dry run: route counts, no sending")
    commands.add_parser("publish", help="publish events for alertable incidents not yet published")
    sync = commands.add_parser("sync-directory", help="subscribers.yaml -> lake JSON")
    sync.add_argument("--path", type=Path, default=directory.SUBSCRIBERS)
    commands.add_parser("report", help="published, delivered, latency")
    args = parser.parse_args(argv)
    since = args.since or datetime.now(UTC)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "decide":
            return dry_run(args.warehouse, since)
        if args.command == "publish":
            return publish_new(args.warehouse, since)
        if args.command == "sync-directory":
            return sync_directory(args.path)
        return report()
    except (
        LakeConfigError,
        ClientError,
        BotoCoreError,
        duckdb.Error,
        directory.DirectoryError,
    ) as e:
        log.error("%s", e)
        return 1
