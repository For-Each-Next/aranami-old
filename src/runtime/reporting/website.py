"""Generate dashboard data and assets from committed inputs."""

from __future__ import annotations

import datetime as dt

from data.newsletter.archive import DEFAULT_PATH, NewsletterDraftArchive
from data.website import read_report_cache, read_timestamp
from runtime.fetch.consistency_repairs import save_dashboard_snapshot
from runtime.fetch.website import DEFAULT_DAYS, DEFAULT_OUTPUT
from runtime.observability.collection_status import collection_run
from tasks.website.collect import collect_dashboard
lazy from webservice.newsletter_charts import prepare_newsletter_charts


def publish(now: dt.datetime) -> None:
    """Assemble the saved dashboard and maintenance proposals."""
    with collection_run("website", trigger="scheduled"):
        snapshot = collect_dashboard(
            now.date(),
            DEFAULT_DAYS,
            only_reports=frozenset(),
            cache_directory=DEFAULT_OUTPUT.parent,
        )
        save_dashboard_snapshot(DEFAULT_OUTPUT, snapshot)


def publish_newsletter() -> None:
    """Generate the draft archive and charts from saved facts.

    Raises:
        FileNotFoundError: No successful newsletter record exists.
    """
    with collection_run("newsletter-daily", trigger="scheduled"):
        record = read_report_cache(
            DEFAULT_OUTPUT.with_name("newsletter.json"),
            "newsletter",
            DEFAULT_DAYS,
            dt.datetime.now(dt.UTC),
        )
        if record is None or record.get("failed") or record["data"] is None:
            message = "The newsletter source observations are unavailable."
            raise FileNotFoundError(message)
        observed = read_timestamp(record["observed_at"])
        NewsletterDraftArchive(DEFAULT_PATH).save(
            record["data"],
            generated_at=observed,
        )
        prepare_newsletter_charts(DEFAULT_OUTPUT.parents[2], record["data"])
