"""Publish all six video-game assessment lists with per-list logging."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING

from data.assessment_lists import AssessmentList
from data.observations import project_snapshot_references
from data.reports import report_key
from data.runtime.report_membership import load_membership, save_membership
from runtime.reporting import ProposedEdit, job_run
from shared.config import TASK_DEFINITIONS
from shared.sources.wiki import preloaded_revision_id, read_pages
from tasks.zhwiki.assessment_lists import (
    analyze,
    collect,
    prepare_data,
    read_assessments,
)
from updater.edit_summary import EditSummary
from updater.services.zhwiki.assessment_lists import (
    prepare_report,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import polars as pl
    from pywikibot import Page
    from pywikibot.site import BaseSite

    from runtime.reporting import JobContext

logger = logging.getLogger(__name__)
ASSESSMENT_LISTS = (
    (
        TASK_DEFINITIONS["assessment_lists"].pages["Bplus"],
        AssessmentList(
            "Category:乙上级电子游戏条目",
            icon_template="Bplus",
        ),
    ),
    (
        TASK_DEFINITIONS["assessment_lists"].pages["BPAN"],
        AssessmentList(
            "Category:请求乙上级评审的电子游戏条目",
            review_grade="bpan",
        ),
    ),
    (
        TASK_DEFINITIONS["assessment_lists"].pages["A"],
        AssessmentList(
            "Category:甲级电子游戏条目",
            icon_template="A",
        ),
    ),
    (
        TASK_DEFINITIONS["assessment_lists"].pages["AL"],
        AssessmentList(
            "Category:甲级列表级电子游戏条目",
            icon_template="AL",
        ),
    ),
    (
        TASK_DEFINITIONS["assessment_lists"].pages["ACC"],
        AssessmentList(
            "Category:请求甲级评审的电子游戏条目",
            review_grade="acc",
        ),
    ),
    (
        TASK_DEFINITIONS["assessment_lists"].pages["PPR"],
        AssessmentList(
            "Category:请求专题评审的电子游戏条目",
            review_grade="ppr",
        ),
    ),
)
type CategoryInputs = tuple[
    AssessmentList,
    dict[str, int | None],
    dict[str, str],
    str,
]
type ListInputs = tuple[str, int | None, CategoryInputs]
type Inputs = tuple[pl.DataFrame, dict[str, ListInputs]]


def fetch(site: BaseSite, _now: dt.datetime) -> Inputs:
    """Read category inputs independently.

    Returns:
        The shared project grades and each successfully read list.
    """
    titles = [title for title, _ in ASSESSMENT_LISTS]
    pages = read_pages(site, titles)
    assessments = read_assessments(site, "电子游戏")
    snapshots = {}
    for (title, config), page in zip(ASSESSMENT_LISTS, pages, strict=True):
        try:
            snapshots[title] = (
                page.text,
                preloaded_revision_id(page),
                collect(site, config, page.text),
            )
        except Exception:
            logger.exception("Could not fetch assessment list %s.", title)
    return assessments, snapshots


def _edit_summary(
    added: Sequence[str],
    removed: Sequence[str],
    count: int,
) -> str:
    """Describe changed articles within the shared summary byte limit.

    Args:
        added: New article titles.
        removed: Removed article titles.
        count: Current number of articles in the report.

    Returns:
        A summary with counts and as many changed links as fit.
    """
    return EditSummary.membership(added, removed, count).render()


def _publish_list(  # ruff: ignore[too-many-arguments] - Share manual and retained inputs.
    active: JobContext,
    title: str,
    config: AssessmentList,
    page: Page | None,
    assessments: pl.DataFrame | None = None,
    *,
    inputs: ListInputs | None = None,
) -> bool:
    """Publish a prepared list and cache its matching local identities.

    Args:
        active: Shared context selecting live publication or preview.
        title: Destination report title and local snapshot identity.
        config: Category and list-rendering configuration.
        page: Destination with preloaded text and revision ID.
        assessments: Current project grades and importance values.
        inputs: Original destination and fetched category observations.

    Returns:
        Whether the destination was saved or verified unchanged.
    """
    if inputs is None:
        original_text = page.text
        original_revision = preloaded_revision_id(page)
    else:
        original_text, original_revision, observations = inputs
    cached = load_membership(active.site, title, original_revision)
    data = (
        prepare_data(
            active.site,
            config,
            original_text,
            assessments=assessments,
            previous_members=cached,
        )
        if inputs is None
        else analyze(
            observations,
            original_text,
            assessments=assessments,
            previous_members=cached,
        )
    )
    report = prepare_report(data, original_text)
    confirmed = active.publish(
        ProposedEdit(
            site=active.site,
            title=title,
            text=report.text,
            summary=_edit_summary(
                data.changes.added,
                data.changes.removed,
                data.changes.count,
            ),
            tags=("assessment-lists",),
            original_text=original_text,
            report_key=(
                report_key("assessment-lists", active.site.dbName(), title)
                if report.result is not None
                else None
            ),
            result=report.result,
        ),
    )
    if confirmed is False and not active.dry:
        return False
    if active.dry:
        save_membership(
            active.site,
            title,
            original_revision,
            data.preview_members,
        )
    else:
        save_membership(
            active.site,
            title,
            active.confirmed_revision(title),
            report.members,
        )
    return confirmed is True


def run(
    *,
    lists: Sequence[tuple[str, AssessmentList]] | None = None,
    dry: bool = False,
    context: JobContext | None = None,
    inputs: Inputs | None = None,
) -> None:
    """Construct and publish each assessment list independently.

    Args:
        lists: Destination titles and content configurations.
            Omit to use the routine defaults.
        dry: Write proposed edits locally instead of editing pages.
        context: Shared routine context, or omit to run independently.
        inputs: Retained assessment and category data.

    Raises:
        ExceptionGroup: If any list fails after remaining lists run.
    """
    with job_run(
        "assessment_lists",
        dry=dry,
        context=context,
    ) as active:
        selected_lists = ASSESSMENT_LISTS if lists is None else lists
        active.register_targets([title for title, _ in selected_lists])
        pages = {}
        observed = {}
        if inputs is None:
            titles = [title for title, _ in selected_lists]
            pages = dict(
                zip(titles, read_pages(active.site, titles), strict=True),
            )
            assessments = read_assessments(active.site, "电子游戏")
        else:
            assessments, observed = inputs
        failures: list[Exception] = []
        confirmed_all = True
        for title, config in selected_lists:
            logger.info("Starting assessment list %s", title)
            try:
                with active.report_attempt(title):
                    confirmed = _publish_list(
                        active,
                        title,
                        config,
                        pages.get(title),
                        assessments,
                        **(
                            {"inputs": observed[title]}
                            if inputs is not None
                            else {}
                        ),
                    )
                    confirmed_all &= confirmed
            except Exception as error:  # Continue independent list updates.
                logger.exception(
                    "Assessment list failed: %s",
                    title,
                )
                failures.append(error)
            else:
                logger.info(
                    "Completed assessment list %s",
                    title,
                )
        if failures:
            message = "Assessment-list updates failed"
            raise ExceptionGroup(message, failures)
        if selected_lists and confirmed_all:
            for reference in project_snapshot_references():
                if (
                    reference["wiki"] == active.site.dbName()
                    and reference["project"] == "电子游戏"
                ):
                    active.confirm_report_date(
                        dt.date.fromisoformat(reference["snapshot_date"]),
                    )
