"""Collect saved analysis in an expendable background worker.

The hourly parent owns execution status and waits for one bounded child.
The child checkpoints shared membership and Parquet summaries. On exit,
its parser, tokenizer and native allocation pools are released.
Imports and ``--help`` never initialize wiki clients or collect sources.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import signal
import subprocess  # ruff: ignore[suspicious-subprocess-import] - Fixed interpreter and worker.
import sys
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from time import monotonic
from typing import TYPE_CHECKING

lazy import pywikibot
lazy from polars.exceptions import PolarsError

from data.runtime.status import get_boot_id, read_status
from runtime.observability.collection_status import collection_run
from runtime.observability.dataset_updates import resumed_dataset_updates
from shared.config import TASK_DEFINITIONS, idle_priority
lazy from data.articles.current_quality import (
    refresh_saved_quality as _refresh_saved_quality,
)
lazy from data.articles.storage import AUTHORSHIP_PATH, HISTORY_PATH
lazy from data.caching.authorship import (
    DEFAULT_PATH as AUTHORSHIP_ATTEMPT_PATH,
)
lazy from data.collection_leases import collection_lease
lazy from runtime.fetch.project_observations import project_cycle
lazy from shared.identity import configure_pywikibot
lazy from shared.sources.quarry.projects import query_pages_by_wikiproject
lazy from tasks.articles.authorship import enrich_authorship
lazy from tasks.articles.authorship_provenance import (
    refresh_current_corrections,
)
lazy from tasks.articles.current_authorship import (
    refresh_current_authorship,
    refresh_current_versions,
)
lazy from tasks.articles.history import retained_article_history
lazy from tasks.articles.quality_analysis import (
    refresh_quality_analysis as collect,
)
lazy from tasks.articles.quality_authors import refresh_quality_author_activity
lazy from tasks.articles.rating_history import refresh_rating_history
lazy from webservice.quality_pages import prepare_quality_pages

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import FrameType

    import polars as pl
    from pywikibot.site import BaseSite

_TASK_ID = "quality-analysis"
_AUTHOR_TASK_ID = "quality-authorship"
_MAX_PAGES = 50
_TIME_BUDGET = 60
_WORKER_TIMEOUT = 180
_TERMINATION_TIMEOUT = 10
_MAX_BOOTSTRAP_PAGES = 500
_MAX_BOOTSTRAP_SECONDS = 300
_AUTHOR_RANGE_PAGES = 120
_AUTHOR_TIME_BUDGET = 360
_AUTHOR_WORKER_TIMEOUT = 480
_LOG = logging.getLogger(__name__)


def refresh_saved_quality(runtime: Path) -> bool:
    """Prepare optional saved views without stopping runtime startup.

    Args:
        runtime: Owner of the retained source facts and report cache.

    Returns:
        Whether a new report was prepared. Invalid or unavailable saved
        inputs are logged and leave the previous generation intact.
    """
    try:
        updated = _refresh_saved_quality(runtime)
        if updated:
            prepare_quality_pages(runtime)
    except (OSError, ValueError, PolarsError) as error:
        _LOG.warning(
            "Saved current-quality projection unavailable (%s).",
            type(error).__name__,
            exc_info=True,
        )
        return False
    else:
        return updated


def publish_saved_quality(runtime: Path) -> None:
    """Generate Article Statistics outputs from saved evidence."""
    _refresh_saved_quality(runtime)
    prepare_quality_pages(runtime)


def _foreground_active(status: dict, now: dt.datetime) -> bool:
    """Check recent observations from foreground jobs.

    Returns:
        Whether a foreground worker has a current active observation.
    """
    foreground = {
        "project-data",
        "newsletter-history",
        "newsletter-daily",
        "website",
        *TASK_DEFINITIONS,
    }
    for row in status.get("executions", {}).values():
        if (
            row.get("task_id") in foreground
            and row.get("outcome") in {"queued", "running"}
            and not row.get("finished_at")
        ):
            updated = dt.datetime.fromisoformat(row["updated_at"])
            if dt.timedelta(0) <= now - updated <= dt.timedelta(seconds=90):
                return True
    return False


def _should_yield(
    runtime: Path,
    owner: str | None,
    stop: Event,
    task_id: str = _TASK_ID,
    *,
    toolforge_job: bool = False,
) -> bool:
    """Stop source admissions for drain or foreground work.

    Returns:
        Whether this worker should leave saved partial progress intact.
    """
    if stop.is_set():
        return True
    if owner is None:
        return False
    now = dt.datetime.now(dt.UTC)
    if now.minute in {59, 0}:
        return True
    status = read_status(runtime)
    if toolforge_job:
        return _foreground_active(status, now)
    scheduler = status.get("services", {}).get("scheduler", {})
    if (
        scheduler.get("boot_id") != owner
        or scheduler.get("lifecycle") != "running"
        or any(
            row.get("queued_since") is not None
            and idle_priority(name) < idle_priority(task_id)
            for schedules in scheduler.get("schedules", {}).values()
            for name, row in schedules.items()
        )
    ):
        return True
    return any(
        row.get("boot_id") == owner
        and row.get("task_id") != task_id
        and row.get("outcome") in {"queued", "running"}
        for row in status.get("executions", {}).values()
    )


def _terminate(child: subprocess.Popen) -> None:
    """Reap the worker before releasing execution ownership."""
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=_TERMINATION_TIMEOUT)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def refresh_quality_analysis(*, toolforge_job: bool = False) -> None:
    """Run one hourly child and release its memory on completion.

    The scheduler serializes this idle routine. The parent retains no
    article bodies, analysis frames or captured output. Both normal
    completion and cancellation reap the child before deployment drain
    can finish. Worker timeouts propagate only after reaping the child.
    Its last atomic Parquet checkpoint remains selected.

    Args:
        toolforge_job: Use foreground observations from separate jobs.
    """
    _run_worker(
        _TASK_ID,
        _MAX_PAGES,
        _TIME_BUDGET,
        _WORKER_TIMEOUT,
        toolforge_job=toolforge_job,
    )


def refresh_quality_authorship(*, toolforge_job: bool = False) -> None:
    """Advance all-grade rating dates and credits in an idle worker.

    Larger bounded passes avoid a two-article hourly cold-cache limit.
    Unchanged talk and article revisions reuse the saved Parquet facts.
    Exiting returns source buffers to the operating system.

    Args:
        toolforge_job: Use foreground observations from separate jobs.
    """
    _run_worker(
        _AUTHOR_TASK_ID,
        _AUTHOR_RANGE_PAGES,
        _AUTHOR_TIME_BUDGET,
        _AUTHOR_WORKER_TIMEOUT,
        toolforge_job=toolforge_job,
    )


def _run_worker(
    task_id: str,
    max_pages: int,
    time_budget: float,
    timeout: float,
    *,
    toolforge_job: bool,
) -> None:
    """Own one bounded child without retaining its data or output.

    Raises:
        subprocess.CalledProcessError: The worker reported a failure.
    """
    runtime = Path.cwd().resolve()
    source = Path(__file__).resolve().parents[2]
    environment = {
        **os.environ,
        "PYTHONPATH": str(source),
        "PYTHONDONTWRITEBYTECODE": "1",
        "POLARS_MAX_THREADS": os.environ.get("POLARS_MAX_THREADS", "2"),
    }
    command = [
        sys.executable,
        "-B",
        "-m",
        "runtime.backfills.quality_analysis",
        "--collect",
        "--task",
        task_id,
        "--runtime",
        str(runtime),
        "--owner-boot",
        get_boot_id(),
        "--max-pages",
        str(max_pages),
        "--time-budget",
        str(time_budget),
    ]
    if toolforge_job:
        environment["ARANAMI_TOOLFORGE_WORKER"] = "1"
    with collection_run(task_id, trigger="scheduled") as execution:
        environment["ARANAMI_DATASET_RUN_ID"] = execution.run_id
        child = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] - Fixed local command.
            command,
            cwd=runtime,
            env=environment,
        )
        try:
            result = child.wait(timeout=timeout)
            if result:
                raise subprocess.CalledProcessError(result, command)
        finally:
            _terminate(child)


def _collect(
    runtime: Path,
    owner: str | None,
    max_pages: int,
    time_budget: float,
    task_id: str = _TASK_ID,
) -> None:
    """Read a shared source cycle and checkpoint saved summaries."""
    stop = Event()
    toolforge_job = os.environ.get("ARANAMI_TOOLFORGE_WORKER") == "1"

    def request_stop(_signal: int, _frame: FrameType | None) -> None:
        """Finish the active request before leaving the worker."""
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    last_check = float("-inf")
    paused = False

    def should_yield() -> bool:
        """Reuse scheduler state for up to one second.

        Returns:
            Whether collection should yield to other work.
        """
        nonlocal last_check, paused
        if stop.is_set():
            return True
        now = monotonic()
        if now - last_check >= 1:
            last_check = now
            paused = _should_yield(
                runtime,
                owner,
                stop,
                task_id,
                toolforge_job=toolforge_job,
            )
        return paused

    if should_yield():
        return
    os.chdir(runtime)
    with (
        collection_lease(runtime, _AUTHOR_TASK_ID)
        if task_id == _AUTHOR_TASK_ID
        else nullcontext(enter_result=True)
    ) as acquired:
        if not acquired:
            return
        configure_pywikibot()
        with (
            resumed_dataset_updates(
                runtime,
                os.environ.get("ARANAMI_DATASET_RUN_ID"),
                task_id,
                owner,
            ),
            project_cycle(now=dt.datetime.now(dt.UTC)),
        ):
            site = pywikibot.Site("zh", "wikipedia")
            membership = query_pages_by_wikiproject(site, "电子游戏")
            if task_id == _AUTHOR_TASK_ID:
                _collect_authorship(
                    site,
                    membership,
                    runtime,
                    max_pages=max_pages,
                    time_budget=time_budget,
                    should_yield=should_yield,
                )
            else:
                collect(
                    site,
                    membership,
                    runtime=runtime,
                    max_pages=max_pages,
                    time_budget=time_budget,
                    should_yield=should_yield,
                )
            if (
                not should_yield()
                and os.environ.get("ARANAMI_FETCH_ONLY") != "1"
            ):
                refresh_saved_quality(runtime)


def _collect_authorship(  # ruff: ignore[too-many-arguments] - Explicit request and time bounds.
    site: BaseSite,
    membership: pl.DataFrame,
    runtime: Path,
    *,
    max_pages: int,
    time_budget: float,
    should_yield: Callable[[], bool],
) -> None:
    """Spend unused range time on attribution within one deadline."""
    deadline = monotonic() + time_budget
    if not should_yield():
        refresh_quality_author_activity(site, runtime=runtime)
    _collect_historical_authorship(
        site,
        membership,
        runtime,
        time_budget=time_budget * 0.25,
        should_yield=should_yield,
    )
    refresh_rating_history(
        site,
        membership,
        runtime=runtime,
        max_requests=max_pages,
        time_budget=time_budget * 0.375,
        should_yield=should_yield,
    )
    refresh_current_authorship(
        site,
        membership,
        runtime=runtime,
        max_requests=max(1, max_pages // 2),
        time_budget=max(0, (deadline - monotonic()) / 2),
        should_yield=should_yield,
    )
    refresh_current_versions(
        site,
        membership,
        runtime=runtime,
        max_requests=max(1, max_pages // 2),
        time_budget=max(0, deadline - monotonic()),
        should_yield=should_yield,
    )


def _collect_historical_authorship(
    site: BaseSite,
    membership: pl.DataFrame,
    runtime: Path,
    *,
    time_budget: float,
    should_yield: Callable[[], bool],
) -> None:
    """Fill reviewed-grade credits during the low-priority idle pass."""
    deadline = monotonic() + time_budget

    def paused() -> bool:
        """Stop before another listing when regular work or time is due.

        Returns:
            Whether the remaining optional source work must wait.
        """
        return monotonic() >= deadline or should_yield()

    if paused():
        return
    events = retained_article_history(runtime / HISTORY_PATH)
    events = enrich_authorship(
        events,
        site,
        path=runtime / AUTHORSHIP_PATH,
        max_requests=10,
        attempt_path=runtime / AUTHORSHIP_ATTEMPT_PATH,
        should_yield=paused,
    )
    if not paused():
        refresh_current_corrections(
            site,
            events,
            membership,
            runtime=runtime,
            max_seconds=max(0, deadline - monotonic()),
            should_yield=paused,
        )


def main(argv: Sequence[str] | None = None) -> None:
    """Validate worker bounds before any source clients are constructed.

    Args:
        argv: Explicit worker arguments, or the process command line.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument(
        "--task",
        choices=(_TASK_ID, _AUTHOR_TASK_ID),
        default=_TASK_ID,
    )
    parser.add_argument("--runtime", type=Path, default=Path.cwd())
    parser.add_argument("--owner-boot")
    parser.add_argument("--max-pages", type=int, default=_MAX_PAGES)
    parser.add_argument("--time-budget", type=float, default=_TIME_BUDGET)
    args = parser.parse_args(argv)
    if not args.collect:
        parser.error("--collect is required to run the background worker")
    maximum_budget = (
        _AUTHOR_TIME_BUDGET
        if args.task == _AUTHOR_TASK_ID
        else _MAX_BOOTSTRAP_SECONDS
    )
    if (
        not 1 <= args.max_pages <= _MAX_BOOTSTRAP_PAGES
        or not 0 < args.time_budget <= maximum_budget
        or (
            args.owner_boot is not None
            and re.fullmatch(r"[0-9a-f]{32}", args.owner_boot) is None
        )
    ):
        parser.error("worker bounds or owner identity are invalid")
    _collect(
        args.runtime.resolve(),
        args.owner_boot,
        args.max_pages,
        args.time_budget,
        args.task,
    )


if __name__ == "__main__":
    main()
