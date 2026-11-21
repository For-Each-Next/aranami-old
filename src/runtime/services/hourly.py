"""Run the scheduled project, fetch, and report services."""

from __future__ import annotations

import datetime as dt
import logging
import os
import signal
import subprocess  # ruff: ignore[suspicious-subprocess-import] - Fixed local worker.
import sys
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING

from data.collection_leases import collection_lease
from data.runtime.logs import open_run_log
from runtime.observability.interrupted_runs import recover_interrupted_runs
from runtime.services.sampling import observe_job
from runtime.services.workloads import ARTICLE_OUTPUT, NEWSLETTER
from shared.toolforge.jobs import (
    ARTICLE_STATISTICS,
    DATA_FETCH,
    JOB_DEFINITIONS,
    PROJECT_HOURLY,
    PROJECT_SNAPSHOT,
    REPORT_WORKLOADS,
    SERVICES,
    WEBSITE_FETCH,
    job_name,
)
from shared.toolforge.state import (
    ACTIVE_PATH,
    GROUPED_PATH,
    completed,
    fetch_outcome,
    hour,
    midnight,
    record_completion,
    record_fetch,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)
_POLL_SECONDS = 5
_WORKLOAD_MINUTES = {
    PROJECT_SNAPSHOT: 8,
    PROJECT_HOURLY: 8,
    "newsletter-history": 10,
    NEWSLETTER: 12,
    "dyks": 12,
    "new_pages": 13,
    "assessment_log": 10,
    "assessment_lists": 9,
    "enwp_key_articles": 10,
    "pageviews": 12,
    "pexbot": 6,
    WEBSITE_FETCH: 11,
    "quality-authorship": 11,
}
_FETCH_ORDER = (
    "newsletter-history",
    "dyks",
    WEBSITE_FETCH,
    NEWSLETTER,
    *(
        name
        for name in REPORT_WORKLOADS
        if name not in {"dyks", NEWSLETTER, "website"}
    ),
)


def enabled(runtime: Path) -> bool:
    """Check the shared scheduler selection.

    Returns:
        Whether grouped services may admit new work.
    """
    return (runtime / ACTIVE_PATH).is_file() and (
        runtime / GROUPED_PATH
    ).is_file()


def _run_child(
    phase: str,
    name: str,
    cycle: dt.datetime,
    seconds: float,
) -> None:
    """Run an isolated workload and reap its descendants.

    Raises:
        subprocess.CalledProcessError: The workload failed.
        subprocess.TimeoutExpired: The workload exceeded its deadline.
    """
    command = [
        sys.executable,
        "-B",
        "-m",
        "runtime.services",
        "--worker",
        phase,
        name,
        cycle.isoformat(),
    ]
    with subprocess.Popen(command, start_new_session=True) as worker:  # ruff: ignore[subprocess-without-shell-equals-true]
        try:
            result = worker.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            os.killpg(worker.pid, signal.SIGKILL)
            raise
        if result:
            raise subprocess.CalledProcessError(result, command)


def _wait(
    runtime: Path,
    ready: Callable[[], bool],
    deadline: dt.datetime,
) -> None:
    """Wait for the current hour's upstream receipt.

    Raises:
        TimeoutError: The service is paused or its deadline has elapsed.
    """
    while not ready():
        if not enabled(runtime) or dt.datetime.now(dt.UTC) >= deadline:
            message = "The current UTC hour's upstream work has not finished."
            raise TimeoutError(message)
        sleep(_POLL_SECONDS)


def _due_cycle(name: str, cycle: dt.datetime) -> dt.datetime:
    """Return the success key used for hourly and daily work."""
    definition = JOB_DEFINITIONS.get(name)
    return midnight(cycle) if definition and definition.hour == "0" else cycle


def _attempt(  # ruff: ignore[too-many-arguments] - Bind the UTC cycle and deadline.
    runtime: Path,
    phase: str,
    name: str,
    cycle: dt.datetime,
    deadline: dt.datetime,
    *,
    checkpoint: dt.datetime | None = None,
) -> bool:
    """Run and checkpoint one due workload.

    Returns:
        Whether this workload is confirmed complete for its cycle.
    """
    receipt = (
        f"fetch-{name}"
        if phase == "fetch" and name != PROJECT_SNAPSHOT
        else name
    )
    expected = checkpoint or cycle
    if completed(runtime, receipt, expected):
        return True
    limit = _WORKLOAD_MINUTES.get(name, 4) * 60
    remaining = min(
        limit,
        (deadline - dt.datetime.now(dt.UTC)).total_seconds(),
    )
    if remaining <= 0 or not enabled(runtime):
        return False
    try:
        _run_child(phase, name, cycle, remaining)
        record_completion(runtime, receipt, expected)
    except OSError, subprocess.SubprocessError:
        _LOGGER.exception("%s of %s will retry.", phase, name)
        return False
    return True


def _ensure_snapshot(
    runtime: Path,
    cycle: dt.datetime,
    deadline: dt.datetime,
) -> None:
    """Recover today's missed snapshot under the daily lease.

    Raises:
        RuntimeError: The daily capture is unavailable.
    """
    boundary = midnight(cycle)
    while not completed(runtime, PROJECT_SNAPSHOT, boundary):
        with collection_lease(
            runtime,
            f"{PROJECT_SNAPSHOT}-service",
        ) as acquired:
            if acquired and _attempt(
                runtime,
                "fetch",
                PROJECT_SNAPSHOT,
                cycle,
                deadline,
                checkpoint=boundary,
            ):
                return
        if (
            acquired
            or not enabled(runtime)
            or dt.datetime.now(dt.UTC) >= deadline
        ):
            message = f"The project snapshot is missing for {boundary.date()}."
            raise RuntimeError(message)
        sleep(_POLL_SECONDS)


def _fetch(runtime: Path, cycle: dt.datetime, deadline: dt.datetime) -> None:
    """Collect sources and signal the result to report update.

    Raises:
        RuntimeError: One or more sources need a retry.
    """
    record_fetch(runtime, cycle, "running")
    outcome = "failed"
    try:
        _ensure_snapshot(runtime, cycle, deadline)
        if not _attempt(runtime, "fetch", PROJECT_HOURLY, cycle, deadline):
            message = f"Project observations failed for {cycle.isoformat()}."
            raise RuntimeError(message)
        failures = []
        for name in _FETCH_ORDER:
            if name in REPORT_WORKLOADS and completed(
                runtime,
                name,
                _due_cycle(name, cycle),
            ):
                continue
            if name == NEWSLETTER and not completed(
                runtime,
                "fetch-newsletter-history",
                cycle,
            ):
                failures.append(name)
                continue
            if not _attempt(runtime, "fetch", name, cycle, deadline):
                failures.append(name)
        _refresh_articles(runtime, cycle, deadline)
        if not failures:
            outcome = "succeeded"
    finally:
        record_fetch(runtime, cycle, outcome)
    if outcome == "failed":
        message = f"Data fetch needs a retry for {', '.join(failures)}."
        raise RuntimeError(message)


def _reports(runtime: Path, cycle: dt.datetime, deadline: dt.datetime) -> None:
    """Wait for fetch and publish each independently available output.

    Raises:
        RuntimeError: One or more outputs need another attempt.
    """
    _wait(
        runtime,
        lambda: (
            fetch_outcome(runtime, cycle) in {"succeeded", "failed"}
            and completed(runtime, f"fetch-{PROJECT_HOURLY}", cycle)
        ),
        deadline,
    )
    failures = []
    for name in REPORT_WORKLOADS:
        due = _due_cycle(name, cycle)
        if completed(runtime, name, due):
            continue
        ready = name == "website" or completed(
            runtime,
            f"fetch-{name}",
            cycle,
        )
        if not ready or not _attempt(
            runtime,
            "analyze",
            name,
            cycle,
            deadline,
            checkpoint=due,
        ):
            failures.append(name)
    if not _attempt(runtime, "analyze", ARTICLE_OUTPUT, cycle, deadline):
        failures.append(ARTICLE_OUTPUT)
    if failures:
        message = f"Report update needs a retry for {', '.join(failures)}."
        raise RuntimeError(message)


def _refresh_articles(
    runtime: Path,
    cycle: dt.datetime,
    deadline: dt.datetime,
) -> None:
    """Collect prose inputs and resume authorship after its backfill."""
    _attempt(runtime, "fetch", "quality-analysis", cycle, deadline)
    with collection_lease(runtime, job_name(ARTICLE_STATISTICS)) as acquired:
        if acquired:
            _attempt(runtime, "fetch", "quality-authorship", cycle, deadline)


def run_service(name: str) -> None:
    """Run a scheduled service using shared ownership and UTC receipts.

    Raises:
        RuntimeError: The project snapshot did not complete.
    """
    runtime = Path.cwd()
    with (
        open_run_log(),
        collection_lease(runtime, f"{name}-service") as acquired,
    ):
        started = dt.datetime.now(dt.UTC)
        cycle = hour(started)
        checkpoint = midnight(cycle) if name == PROJECT_SNAPSHOT else cycle
        allocation = SERVICES[name]
        deadline = min(
            started + dt.timedelta(minutes=allocation.minutes, seconds=-20),
            cycle + dt.timedelta(minutes=58),
        )
        finished = completed(runtime, name, checkpoint) and (
            name != DATA_FETCH
            or completed(runtime, f"fetch-{PROJECT_HOURLY}", cycle)
        )
        if not acquired or not enabled(runtime) or finished:
            return
        with observe_job(runtime, name, started):
            recover_interrupted_runs(before=started)
            if name == PROJECT_SNAPSHOT:
                if not _attempt(
                    runtime,
                    "fetch",
                    name,
                    cycle,
                    deadline,
                    checkpoint=checkpoint,
                ):
                    message = (
                        f"The project snapshot failed for {cycle.isoformat()}."
                    )
                    raise RuntimeError(message)
            elif name == DATA_FETCH:
                _fetch(runtime, cycle, deadline)
                record_completion(runtime, name, cycle)
            else:
                _reports(runtime, cycle, deadline)
                record_completion(runtime, name, cycle)
