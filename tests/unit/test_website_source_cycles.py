"""Verify source reuse across newsletter and website collection."""

# ruff: file-ignore[private-member-access]

from __future__ import annotations

import datetime as dt
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, call, patch

import polars as pl

from runtime.fetch import newsletter_history, website as website_job
from shared.sources.cycle import read_membership, read_top_pageviews
from shared.sources.pageviews import TopPageviews


class WebsiteSourceCycleTests(TestCase):
    """Verify source reuse during independent collection passes."""

    @staticmethod
    def test_hourly_recognition_uses_a_fresh_source_cycle() -> None:
        """Retain project evidence without regenerating drafts."""
        stamp = dt.datetime(2026, 10, 31, 13, tzinfo=dt.UTC)
        clock = Mock(UTC=dt.UTC)
        clock.datetime.now.return_value = stamp
        members = pl.DataFrame({"page_id": [1]})
        fetch = Mock(return_value=members)

        def membership(_site: object, project: str) -> pl.DataFrame:
            """Reuse replica data within this independent pass.

            Returns:
                The current project membership fixture.
            """
            return read_membership("zhwiki", project, fetch)

        def collect(
            _site: object,
            observed: pl.DataFrame,
            *,
            now: dt.datetime,
            path: Path,
        ) -> pl.DataFrame:
            """Check archive settings and repeat a shared metadata read.

            Returns:
                Synthetic recorded events without writing files.
            """
            assert now is stamp
            assert path == Path(
                "data/parsed/article-history.parquet",
            )
            assert observed.equals(members)
            assert read_membership("zhwiki", "电子游戏", fetch).equals(members)
            return pl.DataFrame({"kind": ["dyk", "news"]})

        with (
            patch.object(newsletter_history, "dt", clock),
            patch.object(newsletter_history.pywikibot, "Site") as site,
            patch.object(
                newsletter_history,
                "query_pages_by_wikiproject",
                side_effect=membership,
            ) as query,
            patch.object(
                newsletter_history,
                "history_membership",
                side_effect=lambda _site, observed: observed,
            ) as history_scope,
            patch.object(
                newsletter_history,
                "collect_article_history",
                side_effect=collect,
            ) as archive,
            patch.object(
                newsletter_history,
                "enrich_milestones",
            ) as recognition,
            patch.object(
                newsletter_history,
                "sync_current_assessments",
            ) as assessments,
            patch.object(newsletter_history, "reconcile_scope") as scope,
            patch.object(website_job, "refresh_newsletter") as newsletter,
            patch.object(website_job, "refresh_website") as website,
            patch.object(newsletter_history._LOGGER, "info") as logged,
        ):
            site.return_value.dbName.return_value = "zhwiki"
            newsletter_history.run()
            newsletter_history.run()
        assert fetch.call_count == 2  # ruff: ignore[magic-value-comparison]
        assert site.call_args_list == [call("zh", "wikipedia")] * 2
        assert (
            query.call_args_list == [call(site.return_value, "电子游戏")] * 2
        )
        assert archive.call_count == 2  # ruff: ignore[magic-value-comparison]
        assert history_scope.call_count == 2  # ruff: ignore[magic-value-comparison]
        assert recognition.call_count == 2  # ruff: ignore[magic-value-comparison]
        assert assessments.call_count == 2  # ruff: ignore[magic-value-comparison]
        assert recognition.call_args.kwargs == {"max_requests": 10}
        assert assessments.call_args.args[0].equals(members)
        assert (
            assessments.call_args.args[1] == newsletter_history.MILESTONES_PATH
        )
        assert assessments.call_args.kwargs == {
            "observed_at": stamp,
            "profile": newsletter_history.assessment_profile(
                "zhwiki",
                "电子游戏",
            ),
        }
        assert scope.call_args.args[0].equals(members)
        assert (
            scope.call_args.args[1]
            == newsletter_history.MILESTONES_PATH.parent
        )
        assert scope.call_args.kwargs == {"observed_at": stamp}
        clock.datetime.now.assert_called_with(dt.UTC)
        logged.assert_called_with(
            "Hourly recognition scan retained %d project events.",
            2,
        )
        newsletter.assert_not_called()
        website.assert_not_called()

    @staticmethod
    def test_daily_newsletter_waits_with_an_independent_source_cycle() -> None:
        """Queue daily collection with per-cycle source reuse."""
        fetch = Mock(
            return_value=TopPageviews(
                "zh.wikipedia.org",
                ("2026", "10", "19"),
                pl.DataFrame({"views": [12]}),
            ),
        )

        def collect(*, wait: bool, task_id: str, trigger: str) -> None:
            """Reuse reads within one required boundary collection."""
            assert wait
            assert task_id == "newsletter-daily"
            assert trigger == "scheduled"
            for _ in range(2):
                read_top_pageviews(
                    "zh.wikipedia.org",
                    ("2026", "12", "31"),
                    fetch,
                )

        updater = Mock(refresh=Mock(side_effect=collect))
        website_job.refresh_newsletter(updater)
        website_job.refresh_newsletter(updater)
        assert (
            updater.refresh.call_args_list
            == [
                call(
                    wait=True,
                    task_id="newsletter-daily",
                    trigger="scheduled",
                ),
            ]
            * 2
        )
        fetch.assert_called_once()
