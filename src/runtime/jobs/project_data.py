"""Capture hourly project observations and daily snapshots."""

from __future__ import annotations

import datetime as dt
import logging

import pywikibot

from data import project_data
from data.caching.project_observations import (
    prune as prune_hourly_observations,
)
from runtime.collection_status import collection_run
from runtime.project_observations import (
    collect_project_categories,
    collect_project_membership,
    link_rollover_membership,
)
from shared.config import PROJECT_DATA_SCOPES
from shared.identity import configure_pywikibot
from shared.sources.cycle import source_cycle
from tasks import project_data as project_capture
from tasks.enwiki import talks as english_talks

_LOGGER = logging.getLogger(__name__)


def run(*, now: dt.datetime | None = None) -> None:  # ruff: ignore[complex-structure] - Independent project, rollover and comparison outcomes.
    """Capture configured projects independently before daily consumers.

    Startup recovery captures only the actual current UTC boundary.
    Each project retains its first complete observation independently;
    failure in one project does not prevent the others from completing.

    Args:
        now: Actual UTC start of this collection.

    Raises:
        ExceptionGroup: One or more configured project captures failed.
    """
    instant = now or dt.datetime.now(dt.UTC)
    if instant.date() < project_data.ACTIVATION_DATE:
        return
    configure_pywikibot()
    failures = []
    chinese_members = None
    with (
        collection_run("project-data", trigger="scheduled") as execution,
        source_cycle(),
    ):
        for language, project in PROJECT_DATA_SCOPES:
            try:  # ruff: ignore[too-many-statements-in-try-clause]
                site = pywikibot.Site(language, "wikipedia")
                if instant.hour != 0 or language != "zh":
                    project_capture.capture(site, project, instant.date())
                if language != "zh":
                    if instant.hour == 0 and language == "en":
                        link_rollover_membership(
                            site,
                            project,
                            instant.date(),
                        )
                        english_talks.prune_daily(instant.date())
                    continue
                members = collect_project_membership(
                    site,
                    project,
                    now=instant,
                )
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
    prune_hourly_observations(instant)
