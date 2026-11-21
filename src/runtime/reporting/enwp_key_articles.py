"""Publish both English key-article reports through the run context."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING

from data import enwiki, project_data
from data.key_articles import ReportData
from data.observations import record_page_inputs
from data.reports import report_key
from runtime.reporting import ProposedEdit, job_run
from shared.config import TASK_DEFINITIONS
from shared.sources.wiki import preloaded_revision_id, read_pages
from tasks.enwiki.key_articles import (
    prepare_publication,
    prepare_reports,
    record_publication,
)
from tasks.project_assessments import get_snapshot
from updater.services.zhwiki import enwp_key_articles as reports

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pywikibot.site import BaseSite

    from runtime.reporting import JobContext


REPORT_TARGETS = dict(TASK_DEFINITIONS["enwp_key_articles"].pages)
_LOGGER = logging.getLogger(__name__)


REPORT_SPECS = (
    reports.ImportanceReportSpec(
        name="important",
        filter_column="en_importance",
        accepted_values=("Top", "High"),
        count_markers=(("Top", "count_top"), ("High", "count_high")),
    ),
    reports.QualityReportSpec(
        name="quality",
        filter_column="en_class",
        accepted_values=("FA", "FL", "GA"),
        count_markers=(
            ("FA", "count_fa"),
            ("FL", "count_fl"),
            ("GA", "count_ga"),
        ),
    ),
)


type Inputs = tuple[
    dict[str, tuple[str, int | None]],
    ReportData,
    dt.date | None,
]


def _collect(
    site: BaseSite,
    targets: Mapping[str, str],
    *,
    dry: bool,
) -> Inputs:
    """Read the inputs to both English comparison reports.

    Returns:
        Destination baselines, joined observations and the date.

    Raises:
        ValueError: The daily English membership is missing.
    """
    titles = [targets[spec.name] for spec in REPORT_SPECS]
    snapshot = get_snapshot(
        site,
        "电子游戏",
        observed_at=dt.datetime.now(dt.UTC),
        dry=dry,
    )
    inputs = {}
    boundary = snapshot.manifest["metadata"].get("boundary_date")
    if isinstance(boundary, str):
        english = project_data.read_snapshot(
            "enwiki",
            "Video games",
            dt.date.fromisoformat(boundary),
            dry=dry,
        )
        if english is None:
            message = (
                "English comparisons require the completed "
                "daily English page table."
            )
            raise ValueError(message)
        members = english.tables["members"]
        inputs["english_members"] = members
        record_page_inputs(
            "enwiki",
            "Video games",
            members.rename({
                "rev_id": "page_revision",
                "talk_page_rev": "talk_revision",
            }),
        )
    pages = dict(
        zip(
            (spec.name for spec in REPORT_SPECS),
            read_pages(site, titles),
            strict=True,
        ),
    )
    destinations = {
        name: (page.text, preloaded_revision_id(page))
        for name, page in pages.items()
    }
    existing = {name: original for name, (original, _) in destinations.items()}
    with enwiki.source_scope(dry=dry):
        data = prepare_reports(
            existing,
            tuple(spec.definition for spec in REPORT_SPECS),
            site,
            **inputs,
        )
    day = snapshot.manifest["metadata"].get("snapshot_date")
    return (
        destinations,
        data,
        dt.date.fromisoformat(day) if isinstance(day, str) else None,
    )


def fetch(site: BaseSite, _now: dt.datetime) -> Inputs:
    """Read English comparison observations after the daily snapshot.

    Returns:
        Destinations, joined observations, and the daily report date.
    """
    return _collect(site, REPORT_TARGETS, dry=False)


def run(
    *,
    targets: Mapping[str, str] | None = None,
    dry: bool = False,
    context: JobContext | None = None,
    inputs: Inputs | None = None,
) -> None:
    """Publish English comparisons after retaining daily assessments.

    Reuse or capture the completed day's project assessments before
    preparing either comparison. Concurrent assessment-log collection
    shares the same immutable snapshot. Wiki saves stay independent.

    Args:
        targets: Destination titles keyed by report kind.
            Omit to use the routine defaults.
        dry: Write local proposed edits instead of publishing.
        context: Shared run context, or a standalone job context.
        inputs: Retained English observations for scheduled analysis.

    Raises:
        ExceptionGroup: A publication failed after trying both targets.
    """
    with job_run(
        "enwp_key_articles",
        dry=dry,
        context=context,
    ) as active:
        selected_targets = REPORT_TARGETS if targets is None else targets
        titles = [selected_targets[spec.name] for spec in REPORT_SPECS]
        active.register_targets(titles)
        destinations, data, day = (
            inputs
            if inputs is not None
            else _collect(active.site, selected_targets, dry=active.dry)
        )
        existing = {
            name: original for name, (original, _) in destinations.items()
        }
        texts = reports.build_reports(existing, data, REPORT_SPECS)
        failures: list[Exception] = []
        confirmed_all = True
        for spec in REPORT_SPECS:
            title = selected_targets[spec.name]
            try:  # ruff: ignore[too-many-statements-in-try-clause] - Isolate each attempt.
                with active.report_attempt(title):
                    original_revision = destinations[spec.name][1]
                    prepared = prepare_publication(
                        data,
                        spec.definition,
                        active.site,
                        title,
                        existing[spec.name],
                        original_revision=original_revision,
                    )
                    edit = ProposedEdit(
                        site=active.site,
                        title=title,
                        text=texts[spec.name],
                        summary=reports.build_edit_summary(
                            prepared.changes,
                            data.linked_titles,
                            quality=True,
                            new_nominees=prepared.new_nominees,
                        )
                        if spec.name == "quality"
                        else spec.build_edit_summary(
                            prepared.changes,
                            data.linked_titles,
                        ),
                        tags=("enwp-key-articles", spec.name),
                        original_text=existing[spec.name],
                        report_key=report_key(
                            "english-comparisons",
                            active.site.dbName(),
                            title,
                            variant=spec.name,
                        ),
                        result=reports.report_result(data, spec),
                    )
                    confirmed = active.publish(edit)
                    record_publication(
                        prepared,
                        active.site,
                        title,
                        original_revision,
                        active.confirmed_revision(title),
                        confirmed=confirmed is True,
                        dry=active.dry,
                    )
            except Exception as error:
                _LOGGER.exception(
                    "English-comparison publication failed: %s",
                    title,
                )
                failures.append(error)
            else:
                confirmed_all &= confirmed is True
        if failures:
            message = "English-comparison report publication failed."
            raise ExceptionGroup(message, failures)
        if confirmed_all and day is not None:
            active.confirm_report_date(day)
