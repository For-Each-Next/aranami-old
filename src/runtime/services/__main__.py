"""Launch the Toolforge jobs or emit their definitions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from shared.toolforge.jobs import (
    ARTICLE_STATISTICS,
    JOB_DEFINITIONS,
    MAINTENANCE,
    ON_DEMAND,
    SERVICES,
    job_definitions,
    save_installed_schedules,
)
from shared.toolforge.state import GROUPED_PATH
lazy from runtime.backfills import article_statistics
lazy from runtime.services import hourly, maintenance, workloads

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> None:
    """Parse the public launcher and internal worker command lines."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "name",
        nargs="?",
        choices=tuple(JOB_DEFINITIONS | SERVICES | ON_DEMAND),
    )
    mode.add_argument("--manifest", action="store_true")
    mode.add_argument("--record-schedules", action="store_true")
    mode.add_argument(
        "--worker",
        nargs=3,
        metavar=("PHASE", "WORKLOAD", "CYCLE"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--on-demand", action="store_true")
    parser.add_argument("--weekly-maintenance", action="store_true")
    args = parser.parse_args(argv)
    if args.manifest:
        tool = Path(
            os.environ.get("ARANAMI_TOOL_DIR", "/data/project/aranami"),
        )
        definitions = job_definitions(
            tool,
            on_demand=args.on_demand,
            weekly_maintenance=args.weekly_maintenance,
        )
        print(json.dumps(definitions, indent=2))  # ruff: ignore[print]
    elif args.record_schedules:
        save_installed_schedules(Path.cwd(), json.load(sys.stdin))
    elif args.worker:
        phase, name, selected = args.worker
        cycle = dt.datetime.fromisoformat(selected)
        if phase not in {
            "fetch",
            "analyze",
        } or cycle.utcoffset() != dt.timedelta(0):
            parser.error("Workers require a known phase and UTC hour.")
        workloads.run_workload(phase, name, cycle)
    elif args.name == ARTICLE_STATISTICS:
        article_statistics.run()
    elif args.name == MAINTENANCE:
        maintenance.run()
    elif (Path.cwd() / GROUPED_PATH).is_file() and args.name in SERVICES:
        hourly.run_service(args.name)


if __name__ == "__main__":
    main()
