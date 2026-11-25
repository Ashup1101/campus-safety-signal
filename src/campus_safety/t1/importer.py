"""t1 import: bring a finished run (an Actions artifact, or `t1 rule` output) into the lake
under t1/<run_id>/ after checking its shape. A run whose forecast has other columns, unknown
levels or a method that disagrees with its scorecard is refused. Write-once: importing the same
run again is a no-op; different bytes under the same run id are refused."""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from campus_safety.lake.storage import Lake
from campus_safety.t1 import pipeline, switch

LEVELS = {"quiet", "elevated", "high"}
FILES = ("scorecard.json", "forecast.parquet")


def check(source: Path) -> dict[str, object]:
    card = json.loads((source / "scorecard.json").read_text())
    switch.validate(card)
    found = duckdb.execute(
        "SELECT * FROM read_parquet($p)", {"p": str(source / "forecast.parquet")}
    )
    columns = [c[0] for c in found.description]
    if columns != [name for name, _ in pipeline.FORECAST]:
        raise ValueError(f"forecast columns differ: {columns}")
    rows = found.fetchall()
    if {r[4] for r in rows} - LEVELS:
        raise ValueError("forecast has unknown levels")
    if {r[5] for r in rows} - {card["method"]}:
        raise ValueError("forecast method disagrees with the scorecard method")
    return {"run_id": card["run_id"], "method": card["method"], "rows": len(rows)}


def import_run(lake: Lake, source: Path) -> str:
    summary = check(source)
    prefix = f"t1/{summary['run_id']}/"
    if lake.keys(prefix):
        if all(lake.get(prefix + name) == (source / name).read_bytes() for name in FILES):
            return "unchanged"
        raise ValueError(f"run {summary['run_id']} already imported with different files")
    for name in FILES:
        lake.create(prefix + name, (source / name).read_bytes())
    stamp = {**summary, "imported_at": datetime.now(UTC).isoformat()}
    lake.create(prefix + "import.json", json.dumps(stamp, sort_keys=True).encode())
    return "imported"
