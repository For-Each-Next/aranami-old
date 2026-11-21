"""Advance the Article Statistics backlog until its scan finishes."""

from __future__ import annotations

import datetime as dt
import logging
import subprocess  # ruff: ignore[suspicious-subprocess-import] - Catch errors from the bounded local worker.
from pathlib import Path
from time import sleep

import polars as pl

from data.articles import current_authorship, rating_history
from data.articles.authorship_store import complete_contributor_evidence
from data.collection_leases import collection_lease
from data.runtime.logs import open_run_log
from runtime.services.hourly import enabled
from runtime.services.sampling import observe_job
from runtime.services.workloads import collect_article_inputs
from shared.support.files import atomic_json
from shared.toolforge.jobs import (
    ARTICLE_STATISTICS,
    PROJECT_HOURLY,
    job_name,
)
from shared.toolforge.state import (
    STATE_DIRECTORY,
    completed,
    fetch_outcome,
    hour,
)

_LOGGER = logging.getLogger(__name__)


def authorship_coverage(runtime: Path) -> dict[str, int]:
    """Measure saved attribution and rating data coverage.

    Returns:
        Counts of eligible, covered, and unchecked targets.
    """
    tables = current_authorship.load(runtime)
    targets = pl.concat([
        tables["targets"].select(current_authorship.KEY),
        current_authorship.pending(tables).select(current_authorship.KEY),
    ]).unique()
    missing = targets.join(
        complete_contributor_evidence(tables["evidence"]).select(
            current_authorship.KEY,
        ),
        on=current_authorship.KEY,
        how="anti",
        nulls_equal=True,
    )
    unchecked = missing.join(
        tables["attempts"].select(current_authorship.KEY),
        on=current_authorship.KEY,
        how="anti",
        nulls_equal=True,
    )
    histories = rating_history.load(runtime)["inference"].filter(
        pl.col("talk_page_id").is_not_null()
        & pl.col("scanned_talk_rev_id").is_not_null(),
    )
    pending_history = histories.filter(
        (pl.col("banner_transition_status") != "proven").fill_null(value=True)
        & pl
        .col("reason")
        .is_in({"pending", "bounded_prefix"})
        .fill_null(value=True),
    )
    return {
        "targets": targets.height,
        "attributed": targets.height - missing.height,
        "unchecked": unchecked.height,
        "history_targets": histories.height,
        "history_unchecked": pending_history.height,
    }


def run() -> None:
    """Resume bounded acquisition until the backlog has been checked."""
    runtime = Path.cwd()
    with (
        open_run_log(),
        collection_lease(runtime, job_name(ARTICLE_STATISTICS)) as acquired,
    ):
        if not acquired or not enabled(runtime):
            return
        with observe_job(runtime, ARTICLE_STATISTICS, dt.datetime.now(dt.UTC)):
            while enabled(runtime):
                now = dt.datetime.now(dt.UTC)
                cycle = hour(now)
                if (
                    now.minute in {0, 59}
                    or not completed(runtime, f"fetch-{PROJECT_HOURLY}", cycle)
                    or fetch_outcome(runtime, cycle)
                    not in {"succeeded", "failed"}
                ):
                    sleep(20)
                    continue
                try:
                    collect_article_inputs("quality-authorship")
                except OSError, subprocess.SubprocessError:
                    _LOGGER.exception(
                        "Article Statistics backfill will retry.",
                    )
                    sleep(120)
                    continue
                coverage = authorship_coverage(runtime)
                _LOGGER.info("Article Statistics backfill: %s", coverage)
                done = (
                    coverage["targets"] > 0
                    and coverage["history_targets"] > 0
                    and coverage["unchecked"] == 0
                    and coverage["history_unchecked"] == 0
                )
                atomic_json(
                    runtime
                    / STATE_DIRECTORY
                    / "article-statistics-coverage.json",
                    {**coverage, "done": done, "observed_at": now.isoformat()},
                    max_bytes=2048,
                )
                if done:
                    return
                sleep(15)
