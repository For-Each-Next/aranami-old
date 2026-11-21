"""Audit committed project, website and article coverage on demand."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from data.articles.quality_analysis import load_articles
from data.collection_leases import collection_lease
from data.project_data import ACTIVATION_DATE, read_snapshot
from data.website import read_snapshot as read_website
from runtime.backfills.article_statistics import authorship_coverage
from runtime.services.sampling import observe_job
from shared.config import PROJECT_DATA_SCOPES
from shared.support.files import atomic_json
from shared.toolforge.jobs import (
    DATA_FETCH,
    MAINTENANCE,
    PROJECT_SNAPSHOT,
    REPORT_UPDATE,
)
from shared.toolforge.state import STATE_DIRECTORY, completed, hour

_DAYS = 7


def audit(runtime: Path, now: dt.datetime) -> dict:
    """Audit committed data coverage and freshness.

    Returns:
        Missing snapshots, service checkpoints and saved data coverage.
    """
    missing = []
    for language, project in PROJECT_DATA_SCOPES:
        for offset in range(_DAYS):
            boundary = now.date() - dt.timedelta(days=offset)
            if boundary < ACTIVATION_DATE:
                continue
            try:
                snapshot = read_snapshot(
                    f"{language}wiki",
                    project,
                    boundary,
                    runtime=runtime,
                )
            except OSError, ValueError:
                status = "invalid"
            else:
                status = "missing" if snapshot is None else None
            if status is not None:
                missing.append({
                    "wiki": f"{language}wiki",
                    "project": project,
                    "date": (boundary - dt.timedelta(days=1)).isoformat(),
                    "status": status,
                })
    try:
        website = read_website(runtime / "data/parsed/dashboard.json")
    except OSError, ValueError:
        website = {}
    articles = load_articles(runtime)
    coverage = authorship_coverage(runtime)
    previous = hour(now) - dt.timedelta(hours=1)
    return {
        "observed_at": now.isoformat(),
        "previous_hour": previous.isoformat(),
        "services": {
            name: completed(runtime, name, hour(now))
            or completed(runtime, name, previous)
            for name in (PROJECT_SNAPSHOT, DATA_FETCH, REPORT_UPDATE)
        },
        "snapshot_gaps": missing,
        "website_updated_at": website.get("updated_at"),
        "website_reports": website.get("reports", {}),
        "article_statistics": {
            **coverage,
            "prose_targets": articles.height,
            "prose_measured": articles["prose_characters"].count(),
        },
    }


def run() -> None:
    """Store and print the latest read-only completeness check."""
    runtime = Path.cwd()
    now = dt.datetime.now(dt.UTC)
    with collection_lease(runtime, MAINTENANCE) as acquired:
        if acquired:
            with observe_job(runtime, MAINTENANCE, now):
                result = audit(runtime, now)
                atomic_json(
                    runtime / STATE_DIRECTORY / "completeness.json",
                    result,
                    max_bytes=16 * 1024,
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))  # ruff: ignore[print]
