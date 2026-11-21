"""Verify the typed handoff and analysis's saved-input entry point."""

import datetime as dt
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

import polars as pl

from data.observations import PAGE_INPUT_SCHEMA
from data.pageview_types import PageviewData, RankingData
from data.reports import ReportResult
from data.runtime.report_inputs import load_inputs, save_inputs
from runtime.reporting import new_pages
from runtime.services import workloads

_HOUR = dt.datetime(2026, 11, 21, 19, tzinfo=dt.UTC)


class TestReportInputs(TestCase):
    """Exercise Parquet transfers without external source clients."""

    @staticmethod
    def test_ranking_round_trip() -> None:
        """Preserve nullable typed rows, dates, and metadata."""
        rows = pl.DataFrame({"page_id": [5, 6], "count": [10, None]})
        prepared = PageviewData(
            _HOUR.date(),
            (RankingData("project", "daily", rows, None, None, 2, 10),),
            ReportResult(
                "pageviews",
                {"rankings": rows},
                metadata={"through": _HOUR.date(), "at": _HOUR},
            ),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save_inputs(root, "pageviews", _HOUR, prepared)
            read = load_inputs(root, "pageviews", _HOUR)
        assert read.data_date == prepared.data_date
        assert read.rankings[0].rows.equals(rows)
        assert read.result.metadata == prepared.result.metadata
        assert read.result.tables["rankings"].equals(rows)

    @staticmethod
    def test_completed_report_needs_no_source_calls() -> None:
        """Consume a saved due check without building a wiki client."""
        with (
            TemporaryDirectory() as directory,
            chdir(directory),
            mock.patch.object(new_pages, "read_pages") as source,
            mock.patch.object(new_pages, "run") as report,
        ):
            runtime = Path(directory)
            save_inputs(
                runtime,
                "new_pages",
                _HOUR,
                (_HOUR, [], pl.DataFrame(schema=PAGE_INPUT_SCHEMA)),
            )
            workloads.run_workload("analyze", "new_pages", _HOUR)
        source.assert_not_called()
        report.assert_not_called()
