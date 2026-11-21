"""Dispatch a named on-wiki report against its selected source cycle."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from runtime.fetch.project_observations import DAILY_REPORTS, project_cycle
from runtime.observability.execution import execution_trigger

if TYPE_CHECKING:
    import datetime as dt


def dispatch_scheduled_report(
    name: str,
    *,
    dry: bool,
    now: dt.datetime | None = None,
) -> dt.datetime | None:
    """Invoke automatic work and return its scheduling advice.

    Args:
        name: Independently scheduled routine identifier.
        dry: Suppress publication and production observations.
        now: UTC source cycle selected for this invocation.

    Returns:
        Confirmed completion advice, or null for normal retries.
    """
    callback = import_module(f"runtime.reporting.{name}").run
    options = {"automatic": True} if name in {"new_pages", "pageviews"} else {}
    with (
        execution_trigger("scheduled"),
        project_cycle(daily=name in DAILY_REPORTS, dry=dry, now=now),
    ):
        return callback(dry=dry, **options)
