"""Draw annual newsletter charts from saved observations."""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import warnings
from contextlib import suppress
from functools import cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from opencc import OpenCC
lazy from matplotlib import rc_context
lazy from matplotlib.backends.backend_svg import FigureCanvasSVG
lazy from matplotlib.figure import Figure

from data.newsletter.archive import DEFAULT_PATH, NewsletterDraftArchive
from data.newsletter.grades import (
    CHART_VARIANTS,
    QUALITY_GRADES,
    annual_quality_rows,
    quality_chart_filename,
)
from data.newsletter.observations import OBSERVATIONS_PATH
from data.newsletter.schema import read_newsletter_data
from shared.newsletter import Issue

if TYPE_CHECKING:
    from collections.abc import Mapping

CHART_DIRECTORY = Path("data/webservice/newsletter-charts")
CHART_ROUTE = "/newsletter/charts/"
CHART_NAME = re.compile(
    r"Aranami-quality-\d{4}-(?:zh-hans|zh-tw|zh-hk)-[0-9a-f]{16}\.svg",
    re.ASCII,
)
_LOG = logging.getLogger(__name__)
_CONVERSIONS = {"zh-hans": "t2s", "zh-tw": "s2twp", "zh-hk": "s2hk"}
_LABEL_THRESHOLD = 5


@cache
def _converter(variant: str) -> OpenCC:
    """Reuse one initialized converter per supported Chinese variant.

    Returns:
        The converter for authored chart labels.
    """
    return OpenCC(_CONVERSIONS[variant])


def _title(row: Mapping, variant: str) -> str:
    """Convert a chart title to the selected variant.

    Returns:
        The localized year and measure.
    """
    return _converter(variant).convert(
        f"{row['year']}年条目品质概况",
    )


def _draw(row: Mapping, variant: str, path: Path) -> None:
    """Draw a complete chart, then atomically select its SVG."""
    converter = _converter(variant)
    slices = [
        (count, converter.convert(label), color)
        for key, (label, color) in QUALITY_GRADES.items()
        if (count := row["counts"].get(key, 0)) > 0
    ]
    counts, labels, colors = zip(*slices, strict=True)
    title = _title(row, variant)
    with rc_context({"svg.fonttype": "none", "svg.hashsalt": path.name}):
        figure = Figure(figsize=(7.6, 4.3), facecolor="white")
        figure.text(
            0.5,
            0.937,
            title,
            ha="center",
            fontsize=15,
            fontweight="normal",
        )
        axes = figure.add_axes((0.025, 0.055, 0.48, 0.82))
        wedges, _, _ = axes.pie(
            counts,
            colors=colors,
            startangle=90,
            counterclock=False,
            autopct=lambda share: (
                f"{share:.1f}%" if share >= _LABEL_THRESHOLD else ""
            ),
            pctdistance=0.72,
            wedgeprops={"linewidth": 0.55, "edgecolor": "white"},
            textprops={"fontsize": 10, "color": "#202122"},
        )
        figure.legend(
            wedges,
            [
                f"{label}  {count:,}"
                for label, count in zip(labels, counts, strict=True)
            ],
            loc="center left",
            bbox_to_anchor=(0.525, 0.457),
            frameon=False,
            fontsize=10,
            handlelength=1.05,
            labelspacing=0.5,
        )
        temporary = None
        try:
            with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                with warnings.catch_warnings():
                    # The browser supplies the CJK font.
                    warnings.filterwarnings(
                        "ignore",
                        message=r"Glyph \d+ .* missing from font",
                    )
                    FigureCanvasSVG(figure).print_svg(
                        stream,
                        metadata={"Title": title, "Date": None},
                    )
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def prepare_newsletter_charts(runtime: Path, data: Mapping) -> None:
    """Prepare each distinct image once for the saved issues."""
    directory = runtime / CHART_DIRECTORY
    if directory.is_symlink() or directory.parent.is_symlink():
        _LOG.warning("Annual chart directory must be a regular path.")
        return
    for value, facts in data.get("issues", {}).items():
        issue = Issue.parse(value)
        review = facts.get("year_review")
        if issue.month != 1 or not review:
            continue
        for row in annual_quality_rows(review, issue.year - 1):
            for variant in CHART_VARIANTS:
                path = directory / quality_chart_filename(row, variant)
                if path.is_file() or path.is_symlink():
                    continue
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                    _draw(row, variant, path)
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
    """List saved SVG downloads for the selected annual facts.

    Returns:
        Local image URLs with their language, title and download name.
    """
    directory = runtime / CHART_DIRECTORY
    if directory.is_symlink() or directory.parent.is_symlink():
        return []
    charts = []
    for row in annual_quality_rows(review, issue.year - 1):
        for variant, label in CHART_VARIANTS.items():
            filename = quality_chart_filename(row, variant)
            path = directory / filename
            if path.is_file() and not path.is_symlink():
                charts.append({
                    "url": CHART_ROUTE + filename,
                    "language": variant,
                    "label": label,
                    "title": _title(row, variant),
                    "filename": filename,
                })
    return charts


def backfill_saved_charts(runtime: Path) -> None:
    """Prepare current and historical annual files during an upgrade."""
    retained = read_newsletter_data(runtime / OBSERVATIONS_PATH) or {}
    prepare_newsletter_charts(runtime, retained)
    archive = NewsletterDraftArchive(runtime / DEFAULT_PATH)
    issues = {Issue.parse(value) for value in retained.get("issues", {})}
    issues.add(Issue(dt.datetime.now(dt.UTC).year, 1))
    issues.add(Issue(dt.datetime.now(dt.UTC).year + 1, 1))
    for issue in sorted(issues, key=lambda item: item.value):
        if issue.month != 1:
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
