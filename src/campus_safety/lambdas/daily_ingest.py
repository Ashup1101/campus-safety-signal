"""Lambda: the daily capture, started by EventBridge Scheduler inside AWS.

This account's organization denies iam:CreateOpenIDConnectProvider, so the GitHub Actions ingest
cannot get AWS credentials; the same code runs here instead. It saves the IU crime log page to
bronze (skipped when a snapshot is under 12 hours old) and polls the Phase 2a sources, with the
same robots checks, User-Agent and delays as the CLIs. Logs carry counts only. A failed crime
log capture raises after the poll, so CloudWatch counts it as an error and the scheduler retries.
"""

import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from campus_safety import fetch
from campus_safety.collectors.poll import poll
from campus_safety.collectors.sources import SOURCES
from campus_safety.iu_crime_log import cli as crime_log
from campus_safety.iu_crime_log.parse import ParseError
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake, open_lake

log = logging.getLogger()
log.setLevel(logging.INFO)

SCRATCH = Path("/tmp/campus-safety")  # the only writable path in Lambda  # noqa: S108
MIN_INTERVAL = timedelta(hours=12)


class CaptureError(RuntimeError):
    pass


def run_id(context: object) -> str:
    request = str(getattr(context, "aws_request_id", "") or "manual")
    return f"lambda-{request}"[:64]


def handler(event: dict[str, Any], context: object, lake: Lake | None = None) -> dict[str, Any]:
    os.environ["RUN_ID"] = run_id(context)
    lake = lake or open_lake(os.environ.get("LAKE_URI"))
    crime_log_status = "ok"
    try:
        if crime_log.run(lake, SCRATCH, MIN_INTERVAL) != 0:
            crime_log_status = "invalid"
    except (fetch.FetchError, ParseError) as e:
        crime_log_status = type(e).__name__
    result = poll(lake, SOURCES, bronze.new_run_id())
    summary = {
        "crime_log": crime_log_status,
        "stored": len(result.stored),
        "unchanged": len(result.unchanged),
        "failed": result.reasons,
    }
    log.info(json.dumps(summary))
    if crime_log_status != "ok":
        raise CaptureError(f"crime log capture: {crime_log_status}")
    return summary
