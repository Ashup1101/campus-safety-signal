"""Lambda: S3 "new bronze manifest" events arrive through SQS; count them per source.

Phase 2a wiring only: Phase 2b routes each new object to extraction. Logs carry counts per
source, never object contents. Malformed messages are reported back as batch item failures so
SQS retries them and, after five receives, moves them to the dead-letter queue.
"""

import json
import logging
from collections import Counter
from typing import Any
from urllib.parse import unquote_plus

log = logging.getLogger()
log.setLevel(logging.INFO)


def sources(body: str) -> list[str]:
    """The bronze source of every manifest named in one SQS message body (an S3 event)."""
    event = json.loads(body)
    if event.get("Event") == "s3:TestEvent":  # sent once when the notification is configured
        return []
    found = []
    for record in event["Records"]:
        key = unquote_plus(record["s3"]["object"]["key"])
        parts = key.split("/")
        if "bronze" not in parts or not key.endswith(".manifest.json"):
            raise ValueError("not a bronze manifest event")
        found.append(parts[parts.index("bronze") + 1])
    return found


def handler(event: dict[str, Any], context: object) -> dict[str, list[dict[str, str]]]:
    counts: Counter[str] = Counter()
    failures = []
    for message in event.get("Records", []):
        try:
            counts.update(sources(message["body"]))
        except (KeyError, ValueError, TypeError):
            failures.append({"itemIdentifier": message.get("messageId", "")})
    log.info(json.dumps({"new_manifests": dict(counts), "failed_messages": len(failures)}))
    return {"batchItemFailures": failures}
