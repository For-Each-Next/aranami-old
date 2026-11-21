"""Prepare the saved website and daily newsletter."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from runtime.fetch.consistency_repairs import save_dashboard_snapshot
from runtime.fetch.dashboard import DashboardUpdater, collect_dashboard_pass
from runtime.fetch.project_observations import project_cycle
from runtime.observability.collection_status import collection_run
from tasks.website.collect import REPORT_KEYS, collect_dashboard
lazy from webservice.newsletter_charts import prepare_newsletter_charts

if TYPE_CHECKING:
    import datetime as dt

DEFAULT_OUTPUT = Path("data/parsed/dashboard.json")
DEFAULT_DAYS = 100
_LOGGER = logging.getLogger(__name__)


def dashboard_updater(
    output: Path = DEFAULT_OUTPUT,
    *,
    days: int = DEFAULT_DAYS,
    log_dir: Path = Path("logs"),
    refresh_intervals: dict[str, float] | None = None,
) -> DashboardUpdater:
    """Build a dashboard writer for the hub or a scheduled collector.

    Args:
        output: Saved dashboard destination.
        days: Number of historical UTC dates in the website.
        log_dir: Shared activity and diagnostics directory.
        refresh_intervals: Optional saved dataset refresh intervals.

    Returns:
        A writer whose caller owns its start and stop lifecycle.
    """
    updater = DashboardUpdater(
        output,
        lambda: collect_dashboard_pass(
            updater,
            partial(
                collect_dashboard,
                prepare_newsletter=_prepare_newsletter_assets,
            ),
            save_dashboard_snapshot,
            days,
            refresh_intervals,
        ),
        save_dashboard_snapshot,
        log_dir=log_dir,
        runtime=Path.cwd(),
    )
    return updater


def refresh_website(
    updater: DashboardUpdater,
    *,
    now: dt.datetime | None = None,
) -> bool:
    """Check due website reports in an independent source cycle.

    Args:
        updater: Managed collector serializing overlapping attempts.
        now: UTC source cycle selected for this invocation.

    Returns:
        Whether the saved dashboard refresh completed.
    """
    with project_cycle(now=now):
        return updater.refresh(trigger="scheduled")


def refresh_newsletter(
    updater: DashboardUpdater,
    *,
    now: dt.datetime | None = None,
) -> bool:
    """Collect newsletter history through the latest completed UTC day.

    Args:
        updater: Collector whose active refresh must finish first.
        now: UTC source cycle selected for this invocation.

    Returns:
        Whether the saved newsletter refresh completed.
    """
    with project_cycle(daily=True, now=now):
        return updater.refresh(
            wait=True,
            task_id="newsletter-daily",
            trigger="scheduled",
        )


def _prepare_newsletter_assets(data: dict) -> None:
    """Draw charts after newsletter observations have been saved."""
    try:
        prepare_newsletter_charts(Path.cwd(), data)
    except ImportError, OSError, ValueError:
        _LOGGER.exception("Could not prepare saved newsletter charts.")


def fetch(now: dt.datetime, *, newsletter: bool = False) -> None:
    """Refresh due web source records.

    Raises:
        RuntimeError: One or more of the selected sources failed.
    """
    key = "fetch-newsletter-daily" if newsletter else "website-fetch"
    reports = (
        frozenset({"newsletter"})
        if newsletter
        else frozenset(REPORT_KEYS) - {"newsletter"}
    )
    with (
        collection_run(key, trigger="scheduled"),
        project_cycle(daily=newsletter, now=now),
    ):
        snapshot = collect_dashboard(
            now.date(),
            DEFAULT_DAYS,
            only_reports=reports,
            cache_directory=DEFAULT_OUTPUT.parent,
            draft_archive_path=None,
        )
        if any(snapshot["reports"][report]["failed"] for report in reports):
            message = f"{key} retained one or more failed source checks."
            raise RuntimeError(message)
