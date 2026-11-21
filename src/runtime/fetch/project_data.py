"""Capture hourly project observations and daily snapshots."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING

import pywikibot

from data import project_data
from data.caching.project_observations import (
    prune as prune_hourly_observations,
)
from runtime.fetch.project_observations import (
    collect_project_categories,
    collect_project_membership,
    link_rollover_membership,
)
from runtime.observability.collection_status import collection_run
from shared.config import PROJECT_DATA_SCOPES
from shared.identity import configure_pywikibot
from shared.sources.cycle import source_cycle
from tasks import project_data as project_capture
from tasks.enwiki import talks as english_talks

if TYPE_CHECKING:
    from typing import Literal

    import polars as pl

_LOGGER = logging.getLogger(__name__)


def _collect_project(
    language: str,
    project: str,
    instant: dt.datetime,
    work: Literal["snapshot", "hourly"] | None,
) -> pl.DataFrame | None:
    """Capture one project for the selected service.

    Returns:
        Chinese project membership when needed for hourly categories.
    """
    site = pywikibot.Site(language, "wikipedia")
    boundary = instant.date()
    if work == "snapshot" or (
        work is None and (instant.hour != 0 or language != "zh")
    ):
        project_capture.capture(site, project, boundary)
    if work != "snapshot" and language == "zh":
        return collect_project_membership(site, project, now=instant)
    if instant.hour == 0:
        link_rollover_membership(site, project, boundary)
        if language == "en":
            english_talks.prune_daily(boundary)
    return None


def run(
    *,
    now: dt.datetime | None = None,
    work: Literal["snapshot", "hourly"] | None = None,
) -> None:
    """Capture configured projects independently before daily consumers.

    Startup recovery captures only the actual current UTC boundary.
    Each project retains its first complete observation independently;
    failure in one project does not prevent the others from completing.

    Args:
        now: Actual UTC start of this collection.
        work: Select the daily snapshot or hourly data. The recovery
            scheduler can request both with the default.

    Raises:
        ExceptionGroup: One or more configured project captures failed.
    """
    instant = now or dt.datetime.now(dt.UTC)
    if work == "snapshot":
        instant = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    if instant.date() < project_data.ACTIVATION_DATE:
        return
    configure_pywikibot()
    failures = []
    chinese_members = None
    scopes = (
        (language, project)
        for language, project in PROJECT_DATA_SCOPES
        if work != "hourly" or language == "zh"
    )
    with (
        collection_run(
            "project-hourly" if work == "hourly" else "project-data",
            trigger="scheduled",
        ) as execution,
        source_cycle(),
    ):
        for language, project in scopes:
            try:
                members = _collect_project(language, project, instant, work)
                if project == "电子游戏":
                    chinese_members = members
            except Exception as error:
                _LOGGER.exception("Project snapshot failed: %s", project)
                failures.append(error)
                execution.fail(error)
        if chinese_members is not None:
            try:
                collect_project_categories(
                    pywikibot.Site("zh", "wikipedia"),
                    now=instant,
                    assessment_members=chinese_members,
                )
            except Exception as error:
                _LOGGER.exception("Central category collection failed.")
                failures.append(error)
                execution.fail(error)
    if failures:
        message = "Some daily project snapshots could not be captured."
        raise ExceptionGroup(message, failures)
    if work != "snapshot":
        prune_hourly_observations(instant)
