"""Execute one isolated source or analysis workload for a UTC cycle."""

from __future__ import annotations

import datetime as dt
import logging
import os
from importlib import import_module
from pathlib import Path

lazy import pywikibot

from data.collection_leases import collection_lease
from data.observations import (
    observation_scope,
    page_input_keys,
    project_snapshot_references,
)
from data.runtime.logs import open_run_log
from data.runtime.report_inputs import load_inputs, save_inputs
from runtime.backfills import quality_analysis
from runtime.fetch import newsletter_history, project_data, website as sources
from runtime.fetch.project_observations import DAILY_REPORTS, project_cycle
from runtime.observability.collection_status import collection_run
from runtime.observability.execution import (
    execution_outcomes,
    execution_trigger,
)
from runtime.reporting import website as output
from shared.config import TASK_DEFINITIONS
from shared.identity import configure_pywikibot
from shared.toolforge.jobs import (
    ARTICLE_WORKLOADS,
    FETCH_WORKLOADS,
    PAGEVIEWS,
    PROJECT_HOURLY,
    PROJECT_SNAPSHOT,
    REPORT_WORKLOADS,
    WEB_QUERY,
    WEBSITE_FETCH,
    job_name,
)
lazy from runtime.fetch import article_query

NEWSLETTER = "newsletter-daily"
ARTICLE_OUTPUT = "article-statistics-output"
_LOGGER = logging.getLogger(__name__)
_WORKLOADS = {
    "fetch": {
        PROJECT_SNAPSHOT,
        PROJECT_HOURLY,
        WEB_QUERY,
        NEWSLETTER,
        *FETCH_WORKLOADS,
        *TASK_DEFINITIONS,
        *ARTICLE_WORKLOADS,
    },
    "analyze": {ARTICLE_OUTPUT, PAGEVIEWS, *REPORT_WORKLOADS},
}


def _fetch_report(runtime: Path, name: str, cycle: dt.datetime) -> None:
    """Acquire and retain source inputs for a scheduled wiki report."""
    callback = import_module(f"runtime.reporting.{name}").fetch
    configure_pywikibot()
    with (
        collection_run(f"fetch-{name}", trigger="scheduled"),
        project_cycle(now=cycle, daily=name in DAILY_REPORTS),
    ):
        value = callback(
            pywikibot.Site("zh", "wikipedia"),
            dt.datetime.now(dt.UTC),
        )
        save_inputs(
            runtime,
            name,
            cycle,
            (value, project_snapshot_references(), page_input_keys()),
        )


def _publish_report(runtime: Path, name: str, cycle: dt.datetime) -> None:
    """Analyze retained inputs and verify publication.

    Raises:
        RuntimeError: The report did not confirm completion.
    """
    inputs, snapshots, page_keys = load_inputs(runtime, name, cycle)
    if isinstance(inputs, dt.datetime):
        return
    callback = import_module(f"runtime.reporting.{name}").run
    with (
        observation_scope(snapshots, page_keys),
        execution_trigger("scheduled"),
        execution_outcomes() as outcomes,
    ):
        next_check = callback(inputs=inputs)
    if outcomes != ["success"] or (
        name in {"new_pages", "pageviews"} and next_check is None
    ):
        message = f"{name} still needs a confirmed report update."
        raise RuntimeError(message)


def collect_article_inputs(name: str) -> None:
    """Collect article evidence for later projection."""
    os.environ["ARANAMI_FETCH_ONLY"] = "1"
    callback = (
        quality_analysis.refresh_quality_analysis
        if name == "quality-analysis"
        else quality_analysis.refresh_quality_authorship
    )
    callback(toolforge_job=True)


def _fetch(name: str, cycle: dt.datetime) -> None:
    """Invoke a dataset collector using the selected source boundary."""
    if name == PROJECT_SNAPSHOT:
        project_data.run(now=cycle, work="snapshot")
    elif name == PROJECT_HOURLY:
        project_data.run(now=cycle, work="hourly")
    elif name == WEB_QUERY:
        article_query.run()
    elif name == "newsletter-history":
        newsletter_history.run(now=cycle)
    elif name in {WEBSITE_FETCH, NEWSLETTER}:
        sources.fetch(cycle, newsletter=name == NEWSLETTER)
    elif name in TASK_DEFINITIONS:
        _fetch_report(Path.cwd(), name, cycle)
    else:
        collect_article_inputs(name)


def _analyze(name: str, cycle: dt.datetime) -> None:
    """Calculate and publish outputs from committed inputs."""
    if name in TASK_DEFINITIONS:
        _publish_report(Path.cwd(), name, cycle)
    elif name == NEWSLETTER:
        output.publish_newsletter()
    elif name == "website":
        output.publish(cycle)
    else:
        with collection_run(ARTICLE_OUTPUT, trigger="scheduled"):
            quality_analysis.publish_saved_quality(Path.cwd())


def run_workload(phase: str, name: str, cycle: dt.datetime) -> None:
    """Run a child under the workload lease.

    Raises:
        RuntimeError: Another invocation already owns the workload.
        ValueError: The workload does not belong to this phase.
    """
    if name not in _WORKLOADS.get(phase, ()):
        message = f"Unknown {phase} workload {name!r}."
        raise ValueError(message)
    with (
        open_run_log(),
        collection_lease(Path.cwd(), job_name(name)) as acquired,
    ):
        if not acquired:
            message = f"{name} already owns a live invocation."
            raise RuntimeError(message)
        callback = _fetch if phase == "fetch" else _analyze
        try:
            callback(name, cycle)
        except Exception:
            _LOGGER.exception("Workload %s failed in %s.", name, phase)
            raise
