"""Run one native Toolforge job or emit its deployment definitions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep
from typing import TYPE_CHECKING

from data.collection_leases import collection_lease
from data.runtime.logs import open_run_log
from data.runtime.server_samples import save_job_sample
from runtime.interrupted_runs import recover_interrupted_runs
from shared.config import TASK_DEFINITIONS
from shared.support.files import atomic_json, read_json_object
from shared.support.resources import sample_container
from shared.toolforge_jobs import (
    ACTIVE_PATH,
    ALLOCATIONS,
    JOB_DEFINITIONS,
    STATE_DIRECTORY,
    job_definitions,
    job_name,
    save_installed_schedules,
)
lazy from runtime.jobs import newsletter_history, project_data, website
lazy from runtime.jobs.dispatch import dispatch_scheduled_report
lazy from runtime.quality_analysis import (
    refresh_quality_analysis,
    refresh_quality_authorship,
)
lazy from shared.identity import configure_pywikibot

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_LOGGER = logging.getLogger(__name__)
_RECEIPT_BYTES = 512
_PROJECT_JOB = "project-data"
_HISTORY_JOB = "newsletter-history"
_SAMPLE_SECONDS = 10


def _receipt_path(runtime: Path, name: str) -> Path:
    """Locate a known job's last successful invocation.

    Returns:
        The receipt path beneath the shared state directory.
    """
    return runtime / STATE_DIRECTORY / f"{name}.json"


def _completed(runtime: Path, name: str, cycle: dt.datetime) -> bool:
    """Check for an accepted receipt for this UTC cycle.

    Returns:
        Whether the job completed the requested cycle.
    """
    try:
        receipt = read_json_object(
            _receipt_path(runtime, name),
            _RECEIPT_BYTES,
        )
    except FileNotFoundError:
        return False
    return receipt == {"cycle": cycle.isoformat()}


def _wait_for_inputs(
    runtime: Path,
    name: str,
    cycle: dt.datetime,
) -> None:
    """Wait for inputs from the selected UTC hour.

    Raises:
        TimeoutError: A required input is still missing at the deadline.
    """
    if name == _PROJECT_JOB:
        return
    required = (
        (_PROJECT_JOB, _HISTORY_JOB)
        if name == "newsletter-daily"
        else (_PROJECT_JOB,)
    )
    # Leave part of the Toolforge deadline available for real work.
    remaining = cycle + dt.timedelta(hours=1) - dt.datetime.now(dt.UTC)
    deadline = monotonic() + min(
        ALLOCATIONS[name].minutes * 20,
        remaining.total_seconds(),
    )
    while True:
        missing = [
            source
            for source in required
            if not _completed(runtime, source, cycle)
        ]
        if not missing:
            return
        if monotonic() >= deadline or not (runtime / ACTIVE_PATH).is_file():
            message = (
                f"Waiting for {', '.join(missing)} in {cycle.isoformat()}."
            )
            raise TimeoutError(message)
        sleep(5)


def _execute(name: str, now: dt.datetime) -> None:
    """Dispatch one workload using its existing collector or updater."""
    if name in TASK_DEFINITIONS:
        configure_pywikibot()
        dispatch_scheduled_report(name, dry=False, now=now)
    elif name in {"website", "newsletter-daily"}:
        website.run(name, now=now)
    elif name == _PROJECT_JOB:
        project_data.run(now=now)
    elif name == _HISTORY_JOB:
        newsletter_history.run(now=now)
    elif name == "quality-analysis":
        refresh_quality_analysis(toolforge_job=True)
    else:
        refresh_quality_authorship(toolforge_job=True)


@contextmanager
def _observe_job(
    runtime: Path,
    name: str,
    started: dt.datetime,
) -> Iterator[None]:
    """Sample this container during one owned invocation."""
    stopped = Event()

    def record(outcome: str) -> None:
        """Publish optional readings independently of the work."""
        try:
            save_job_sample(
                runtime,
                name,
                started,
                outcome,
                sample_container(),
            )
        except OSError, ValueError:
            _LOGGER.warning("Could not record resource usage for %s.", name)

    def sample() -> None:
        """Refresh live usage until the invocation finishes."""
        while not stopped.wait(_SAMPLE_SECONDS):
            record("running")

    record("running")
    monitor = Thread(target=sample, daemon=True)
    monitor.start()
    outcome = "failed"
    try:
        yield
        outcome = "succeeded"
    finally:
        stopped.set()
        monitor.join()
        record(outcome)


def run_job(name: str) -> None:
    """Run an enabled workload using the current committed source cycle.

    Args:
        name: Configured collection or report identifier.

    Raises:
        ValueError: The job identifier is invalid.
    """
    if name not in ALLOCATIONS:
        message = f"Unknown Toolforge workload {name!r}."
        raise ValueError(message)
    runtime = Path.cwd()
    active = runtime / ACTIVE_PATH
    if not active.is_file():
        _LOGGER.info("Individual Toolforge jobs are paused.")
        return
    with open_run_log(), collection_lease(runtime, job_name(name)) as acquired:
        now = dt.datetime.now(dt.UTC)
        cycle = now.replace(minute=0, second=0, microsecond=0)
        completed_cycle = (
            cycle
            if JOB_DEFINITIONS[name].hour == "*"
            else cycle.replace(hour=0)
        )
        if not acquired or _completed(runtime, name, completed_cycle):
            _LOGGER.info("Job %s already owns or completed this cycle.", name)
            return
        with _observe_job(runtime, name, now):
            _wait_for_inputs(runtime, name, cycle)
            if not active.is_file():
                return
            recover_interrupted_runs(before=now)
            _execute(name, now)
            atomic_json(
                _receipt_path(runtime, name),
                {"cycle": completed_cycle.isoformat()},
                max_bytes=_RECEIPT_BYTES,
            )


def main(argv: Sequence[str] | None = None) -> None:
    """Validate arguments before loading any report or source clients.

    Args:
        argv: Explicit arguments, or the current command line.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("name", nargs="?", choices=tuple(ALLOCATIONS))
    mode.add_argument("--manifest", action="store_true")
    mode.add_argument("--record-schedules", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.manifest:
        tool_directory = Path(
            os.environ.get("ARANAMI_TOOL_DIR", "/data/project/aranami"),
        )
        print(json.dumps(job_definitions(tool_directory), indent=2))  # ruff: ignore[print]
    elif arguments.record_schedules:
        save_installed_schedules(Path.cwd(), json.load(sys.stdin))
    else:
        run_job(arguments.name)


if __name__ == "__main__":
    main()
