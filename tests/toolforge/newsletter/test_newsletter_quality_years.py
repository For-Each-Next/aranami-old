"""Verify annual promotion cohorts and annual chart inputs."""

from __future__ import annotations

import datetime as dt
from copy import deepcopy
from unittest import TestCase

import mwparserfromhell
import polars as pl
from matplotlib.figure import Figure
from opencc import OpenCC

from data.newsletter.figures import annual_figures
from data.newsletter.grades import QUALITY_HISTORY_GRADES
from data.newsletter.schema import valid_newsletter
from newsletter.test_newsletter_data import Reader
from shared.newsletter import Issue
from tasks.zhwiki.newsletter.annual import prepare_quality_year_ends
from tasks.zhwiki.newsletter.collection import collect_source_facts
from updater.services.newsletter_editorial import render_annual_feature
from webservice import newsletter_png


def _events() -> pl.DataFrame:
    """Build additions, removals, repeated evidence, and unknown dates.

    Returns:
        Complete historical events independent of current assessments.
    """
    rows = [
        ("Former GA", "GA", "added", dt.date(2012, 1, 1)),
        ("Former GA", "GA", "added", dt.date(2012, 1, 1)),
        ("Former GA", "GA", "removed", dt.date(2013, 1, 1)),
        ("Former FA", "FA", "added", dt.date(2012, 2, 1)),
        ("Former FA", "FA", "removed", dt.date(2014, 1, 1)),
        ("Featured list", "FL", "added", dt.date(2012, 3, 1)),
        ("A article", "A", "added", dt.date(2026, 1, 1)),
        ("A list", "AL", "added", dt.date(2026, 1, 2)),
        ("Bplus article", "Bplus", "added", dt.date(2026, 1, 3)),
        ("Former GA", "GA", "added", dt.date(2026, 1, 4)),
        ("Boundary", "GA", "added", dt.date(2026, 2, 1)),
        ("Undated", "FA", "added", None),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "title": pl.String,
            "grade": pl.String,
            "action": pl.String,
            "date": pl.Date,
        },
        orient="row",
    ).with_columns(
        pl.lit("quality").alias("kind"),
        pl.lit(1).alias("revision_id"),
        pl.lit("Stub").alias("current_class"),
    )


class NewsletterQualityYearTests(TestCase):
    """Classify annual cohorts independently of current grades."""

    @staticmethod
    def test_historical_cohorts_keep_promotions_in_their_original_year() -> (
        None
    ):
        """Count each cohort once without carrying earlier articles."""
        events = _events()
        original = events.clone()
        rows = prepare_quality_year_ends(events, dt.date(2026, 2, 1))
        assert rows == [
            {
                "year": 2012,
                "grades": {
                    "FA": 1,
                    "FL": 1,
                    "A": 0,
                    "AL": 0,
                    "GA": 1,
                    "Bplus": 0,
                },
            },
            *(
                {
                    "year": year,
                    "grades": {
                        "FA": 0,
                        "FL": 0,
                        "A": 0,
                        "AL": 0,
                        "GA": 0,
                        "Bplus": 0,
                    },
                }
                for year in range(2013, 2026)
            ),
            {
                "year": 2026,
                "grades": {
                    "FA": 0,
                    "FL": 0,
                    "A": 1,
                    "AL": 1,
                    "GA": 1,
                    "Bplus": 1,
                },
            },
        ]
        assert events.equals(original)

    @staticmethod
    def test_unknown_history_dates_and_empty_years_stay_distinct() -> None:
        """Keep missing dates and histories unavailable."""
        assert prepare_quality_year_ends(None, dt.date(2027, 1, 1)) is None
        assert (
            prepare_quality_year_ends(_events().clear(), dt.date(2027, 1, 1))
            == []
        )
        undated = _events().filter(pl.col("date").is_null())
        assert prepare_quality_year_ends(undated, dt.date(2027, 1, 1)) == []

    @staticmethod
    def test_collector_retains_all_years_and_optional_schema() -> None:
        """Validate six-grade counts and accept legacy snapshots."""
        result = collect_source_facts(
            Reader(),
            now=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
            article_history=_events(),
        )
        years = result["issues"]["2027-01"]["year_review"]["quality_year_ends"]
        assert years == prepare_quality_year_ends(
            _events(),
            dt.date(2026, 2, 1),
        )
        assert valid_newsletter(result)
        for invalid in (
            [*years, years[0]],
            list(reversed(years)),
            [
                {
                    "year": 2027,
                    "grades": dict.fromkeys(QUALITY_HISTORY_GRADES, 0),
                },
            ],
            [{"year": 2026, "grades": {"FA": 1}}],
            [
                {
                    "year": 2026,
                    "grades": dict.fromkeys(QUALITY_HISTORY_GRADES, -1),
                },
            ],
            [
                {
                    "year": 2026,
                    "grades": dict.fromkeys(QUALITY_HISTORY_GRADES, True),
                },
            ],
            "unknown",
        ):
            changed = deepcopy(result)
            changed["issues"]["2027-01"]["year_review"][
                "quality_year_ends"
            ] = invalid
            assert not valid_newsletter(changed)
        legacy = deepcopy(result)
        del legacy["issues"]["2027-01"]["year_review"]["quality_year_ends"]
        legacy["issues"]["2027-01"]["year_review"]["quality_years"] = years
        assert valid_newsletter(legacy)

    @staticmethod
    def test_chart_uses_separate_full_inventory_from_saved_parquet() -> None:
        """Keep recognitions outside current membership scope."""
        result = collect_source_facts(
            Reader(),
            now=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
            article_history=_events().clear(),
            quality_history=_events(),
        )
        review = result["issues"]["2027-01"]["year_review"]
        assert review["quality_changes"] == []
        assert review["quality_year_ends"] == prepare_quality_year_ends(
            _events(),
            dt.date(2026, 2, 1),
        )

    @staticmethod
    def test_figure_preserves_stack_order_and_issue_names() -> None:
        """Keep data series ordered and link each localized image."""
        review = {
            "quality_year_ends": [
                {
                    "year": 2025,
                    "grades": dict.fromkeys(
                        ("FA", "FL", "A", "AL", "GA", "Bplus"),
                        0,
                    ),
                },
                {
                    "year": 2026,
                    "grades": {
                        "FA": 1,
                        "FL": 2,
                        "A": 3,
                        "AL": 4,
                        "GA": 6,
                        "Bplus": 5,
                    },
                },
            ],
        }
        chart = annual_figures(review, 2026)[1]
        assert chart.axis == (2025, 2026)
        assert tuple(series.counts for series in chart.series) == (
            (0, 3),
            (0, 7),
            (0, 6),
            (0, 5),
        )
        assert tuple(series.label for series in chart.series) == (
            "典范级",
            "甲级",
            "优良级",
            "乙上级",
        )
        assert tuple(series.color for series in chart.series) == (
            "#9CBDFF",
            "#66FFFF",
            "#66FF66",
            "#8CFF66",
        )
        text = render_annual_feature(Issue(2027, 1), review)
        code = mwparserfromhell.parse(text)
        chart = next(
            template
            for template in code.filter_templates()
            if template.name.matches("Graph:Chart")
        )
        assert chart.get("type").value.strip() == "stackedrect"
        picture = mwparserfromhell.parse(
            code.filter_comments()[0].contents,
        ).filter_templates()[0]
        for variant in ("zh-cn", "zh-hk", "zh-tw"):
            assert picture.get(variant).value == (
                f"WPVG Newsletter 202701 Feature Graph 1 ({variant}).png"
            )
        assert picture.get("1").value == "600px"
        assert picture.get("2").value == "center"
        assert picture.get("class").value == "skin-invert-image"

    @staticmethod
    def test_stack_axis_expands_instead_of_clipping_large_cohorts() -> None:
        """Keep ten-unit bounds above an observed stack over fifty."""
        review = {
            "quality_year_ends": [
                {
                    "year": 2026,
                    "grades": {
                        **dict.fromkeys(QUALITY_HISTORY_GRADES, 0),
                        "GA": 64,
                    },
                },
            ],
        }
        chart = annual_figures(review, 2026)[1]
        figure = Figure()
        newsletter_png._quality_history(  # ruff: ignore[private-member-access]
            figure,
            chart,
            OpenCC("t2s"),
        )
        assert figure.axes[0].get_ylim() == (0, 70)
        assert chart.series[1].counts == (64,)

    @staticmethod
    def test_all_zero_a_group_is_absent_and_missing_history_stays_blank() -> (
        None
    ):
        """Hide an unused A layer without replacing missing history."""
        review = {
            "quality_year_ends": [
                {
                    "year": 2025,
                    "grades": {
                        "FA": 1,
                        "FL": 2,
                        "A": 0,
                        "AL": 0,
                        "GA": 6,
                        "Bplus": 5,
                    },
                },
            ],
        }
        chart = annual_figures(review, 2026)[1]
        assert chart.axis == (2025,)
        assert tuple(series.counts for series in chart.series) == (
            (3,),
            (6,),
            (5,),
        )
        assert all(series.label != "甲级" for series in chart.series)
        missing = render_annual_feature(Issue(2027, 1), {})
        assert "Feature Graph 1" not in missing
