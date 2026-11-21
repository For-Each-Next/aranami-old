"""Retain annual newsletter PNGs and reproducible Python sources."""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from contextlib import suppress
from functools import cache
from hashlib import sha256
from pathlib import Path
from pprint import pformat
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from data.newsletter.archive import DEFAULT_PATH, NewsletterDraftArchive
from data.newsletter.figures import (
    CHART_VARIANTS,
    FIRST_PNG_ISSUE,
    annual_figures,
    figure_filename,
)
from data.newsletter.historical import with_canonical_dyk_series
from data.newsletter.observations import OBSERVATIONS_PATH
from data.newsletter.schema import read_newsletter_data
from shared.newsletter import Issue
from shared.support.files import encode_json
lazy from webservice.newsletter_png import localized_title, save_feature_png

if TYPE_CHECKING:
    from collections.abc import Mapping

    from data.newsletter.figures import AnnualFigure

CHART_DIRECTORY = Path("data/webservice/newsletter-charts")
CHART_ROUTE = "/newsletter/charts/"
FONT_ASSETS = {
    "newsletter-font.otf": "font/otf",
    "newsletter-font.LICENSE": "text/plain; charset=utf-8",
}
CHART_NAME = re.compile(
    r"Aranami-(?:newsletter-\d{4}01-[1-3]-zh-(?:cn|hk|tw)-[0-9a-f]{16}\.(?:png|py)"
    r"|quality-\d{4}-zh-(?:hans|tw|hk)-[0-9a-f]{16}\.svg)",
    re.ASCII,
)
_LOG = logging.getLogger(__name__)


def _cached_filename(issue: Issue, chart: AnnualFigure, variant: str) -> str:
    """Bind a filename to the chart's saved facts.

    Returns:
        A cache name distinct for each image or rendering contract.
    """
    digest = sha256(encode_json([_renderer()[1], chart])).hexdigest()[:16]
    name = f"Aranami-newsletter-{issue.year}01-{chart.number}-{variant}"
    return f"{name}-{digest}.png"


@cache
def _renderer() -> tuple[str, str]:
    """Read the code and identify the figure format.

    Returns:
        Standalone module text and its SHA-256 digest.
    """
    source = Path(__file__).with_name("newsletter_png.py").read_text("utf-8")
    return source, sha256(source.encode()).hexdigest()


def _save_chart_source(
    chart: AnnualFigure,
    variant: str,
    issue: Issue,
    path: Path,
) -> None:
    """Save the plot code with the exact inputs."""
    inputs = chart._asdict()
    inputs["series"] = [series._asdict() for series in chart.series]
    filename = figure_filename(issue.year, chart.number, variant)
    literal = pformat(inputs, sort_dicts=False, indent=4)
    body = literal.replace("\n", "\n    ")
    source = (
        _renderer()[0]
        + f"""

if __name__ == "__main__":
    from types import SimpleNamespace

    inputs = {body}
    inputs["series"] = [
        SimpleNamespace(**row) for row in inputs["series"]
    ]
    figure = SimpleNamespace(**inputs)
    output = Path(__file__).resolve().with_name({filename!r})
    save_feature_png(figure, {variant!r}, output)
"""
    )
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(source.encode())
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _uses_pngs(issue: Issue) -> bool:
    """Identify annual drafts since the published January 2026 issue.

    Returns:
        Whether the issue is eligible for locally rendered PNGs.
    """
    return issue.month == 1 and issue.year >= FIRST_PNG_ISSUE


def prepare_newsletter_charts(runtime: Path, data: Mapping) -> None:
    """Prepare images and sources from saved annual facts."""
    directory = runtime / CHART_DIRECTORY
    if directory.is_symlink() or directory.parent.is_symlink():
        _LOG.warning("Annual chart directory must be a regular path.")
        return
    for value, facts in data.get("issues", {}).items():
        issue = Issue.parse(value)
        review = facts.get("year_review")
        if not _uses_pngs(issue) or not review:
            continue
        year = issue.year - 1
        try:
            review = with_canonical_dyk_series(runtime, review, year)
        except OSError, ValueError:
            _LOG.exception("Could not read DYK figure data for %s.", value)
        for chart in annual_figures(review, year).values():
            for variant in CHART_VARIANTS:
                path = directory / _cached_filename(issue, chart, variant)
                source = path.with_suffix(".py")
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                    if not path.is_file() and not path.is_symlink():
                        save_feature_png(chart, variant, path)
                    if not source.is_file() and not source.is_symlink():
                        _save_chart_source(chart, variant, issue, source)
                except OSError, ValueError:
                    _LOG.exception(
                        "Could not save annual newsletter chart %s.",
                        path.name,
                    )


def available_charts(
    runtime: Path,
    issue: Issue,
    review: Mapping,
) -> list[dict]:
    """List saved PNGs and Python sources for the WikiProject.

    Returns:
        Immutable asset URLs with the requested wiki filenames.
    """
    directory = runtime / CHART_DIRECTORY
    if (
        not _uses_pngs(issue)
        or directory.is_symlink()
        or directory.parent.is_symlink()
    ):
        return []
    charts = []
    for chart in annual_figures(review, issue.year - 1).values():
        for variant, label in CHART_VARIANTS.items():
            name = _cached_filename(issue, chart, variant)
            path = directory / name
            if path.is_file() and not path.is_symlink():
                source = path.with_suffix(".py")
                charts.append({
                    "url": CHART_ROUTE + name,
                    "language": variant,
                    "label": label,
                    "title": localized_title(chart, variant),
                    "source_url": CHART_ROUTE + source.name
                    if source.is_file() and not source.is_symlink()
                    else None,
                    "filename": figure_filename(
                        issue.year,
                        chart.number,
                        variant,
                    ),
                })
    return charts


def backfill_saved_charts(runtime: Path) -> None:
    """Prepare assets from current and dated annual facts."""
    retained = read_newsletter_data(runtime / OBSERVATIONS_PATH) or {}
    prepare_newsletter_charts(runtime, retained)
    archive = NewsletterDraftArchive(runtime / DEFAULT_PATH)
    issues = {Issue.parse(value) for value in retained.get("issues", {})}
    issues.add(Issue(dt.datetime.now(dt.UTC).year, 1))
    issues.add(Issue(dt.datetime.now(dt.UTC).year + 1, 1))
    for issue in sorted(issues, key=lambda item: item.value):
        if not _uses_pngs(issue):
            continue
        for date in archive.feature_dates(issue):
            with suppress(FileNotFoundError):
                record = archive.read_feature(
                    issue,
                    dt.date.fromisoformat(date),
                )
                if record is not None:
                    prepare_newsletter_charts(
                        runtime,
                        {"issues": {issue.value: record}},
                    )


if __name__ == "__main__":
    backfill_saved_charts(Path.cwd())
