"""Lambda: one per channel queue. Each SQS message is an incident.confirmed event; the handler
loads the incident snapshot and the directory from the lake, picks the recipients, claims one
delivery per subscriber in the write-once ledger, and sends through the channel. A claim that
already exists means another run delivered it: nothing is sent twice. Malformed events are
reported as batch item failures (SQS retries, then the DLQ). Logs carry counts only.
"""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from campus_safety.alerts import events, snapshots
from campus_safety.alerts.channels import Channel, ChannelError, LogChannel, ResendEmail
from campus_safety.alerts.directory import Entry
from campus_safety.alerts.ledger import LakeLedger, Ledger, delivery_key
from campus_safety.alerts.rules import Incident, recipients, render
from campus_safety.lake.storage import Lake, open_lake

log = logging.getLogger()
log.setLevel(logging.INFO)

CHANNEL_VAR = "ALERT_CHANNEL"


@dataclass
class Outcome:
    delivered: int = 0
    already: int = 0
    skipped: int = 0  # recipients without an address on this channel
    failed: int = 0


def deliver(
    event: events.IncidentConfirmed,
    incident: Incident,
    entries: list[Entry],
    channel: Channel,
    ledger: Ledger,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Outcome:
    outcome = Outcome()
    draft = render(incident, event.kind)
    chosen = recipients(incident, [e.subscriber for e in entries])
    by_id = {e.subscriber.subscriber_id: e for e in entries}
    for subscriber in chosen:
        address = by_id[subscriber.subscriber_id].addresses.get(channel.name)
        if address is None:
            outcome.skipped += 1
            continue
        key = delivery_key(event.incident_id, event.kind, subscriber.subscriber_id, channel.name)
        if not ledger.claim(key, now(), event.official_at):
            outcome.already += 1
            continue
        try:
            channel.send(address, draft)
        except ChannelError:
            outcome.failed += 1
            continue
        outcome.delivered += 1
    return outcome


def make_channel(name: str) -> Channel:
    if name == "email":
        return ResendEmail()
    return LogChannel(name)  # web_push / iphone_push arrive in Phase 10


def handler(event: dict[str, Any], context: object, lake: Lake | None = None) -> dict[str, Any]:
    lake = lake or open_lake(os.environ.get("LAKE_URI"))
    channel = make_channel(os.environ.get(CHANNEL_VAR, "log"))
    ledger = LakeLedger(lake)
    entries = snapshots.load_directory(lake)
    totals, failures = Outcome(), []
    for message in event.get("Records", []):
        try:
            confirmed = events.parse(message["body"])
            incident = snapshots.load_incident(lake, confirmed.incident_id)
            if incident is None:
                raise events.EventError("no incident snapshot")
        except (events.EventError, KeyError, TypeError):
            failures.append({"itemIdentifier": message.get("messageId", "")})
            continue
        outcome = deliver(confirmed, incident, entries, channel, ledger)
        totals.delivered += outcome.delivered
        totals.already += outcome.already
        totals.skipped += outcome.skipped
        totals.failed += outcome.failed
    log.info(
        json.dumps({"channel": channel.name, **totals.__dict__, "bad_messages": len(failures)})
    )
    return {"batchItemFailures": failures}
