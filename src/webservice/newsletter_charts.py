"""Render localized newsletter figures from saved facts."""

from __future__ import annotations

import datetime as dt
import logging
import math
import os
import re
from contextlib import suppress
from functools import cache
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from opencc import OpenCC
lazy from matplotlib import dates, font_manager, rc_context
lazy from matplotlib.backends.backend_agg import FigureCanvasAgg
lazy from matplotlib.figure import Figure
lazy from matplotlib.ticker import MaxNLocator

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

if TYPE_CHECKING:
    from collections.abc import Mapping

    from matplotlib.axes import Axes

    from data.newsletter.figures import AnnualFigure

CHART_DIRECTORY = Path("data/webservice/newsletter-charts")
CHART_ROUTE = "/newsletter/charts/"
CHART_NAME = re.compile(
    r"Aranami-(?:newsletter-\d{4}01-[1-3]-zh-(?:cn|hk|tw)-[0-9a-f]{16}\.png"
    r"|quality-\d{4}-zh-(?:hans|tw|hk)-[0-9a-f]{16}\.svg)",
    re.ASCII,
)
_LOG = logging.getLogger(__name__)
_CONVERSIONS = {"zh-cn": "t2s", "zh-tw": "s2twp", "zh-hk": "s2hk"}
_FONT_FILE = Path(__file__).with_name("newsletter-font.otf")
_FIGURE_SIZE = {1: (8.6, 4.6), 2: (7.2, 4.25), 3: (7.2, 4.3)}
_LABEL_THRESHOLD = 5
_QUALITY_AXIS_STEP = 10
_QUALITY_AXIS_MINIMUM_MAX = 50
_MAX_YEARS_WITH_MONTH_TICKS = 4


@cache
def _converter(variant: str) -> OpenCC:
    """Reuse a converter for each supported Chinese edition.

    Returns:
        The script and vocabulary converter for the selected edition.
    """
    return OpenCC(_CONVERSIONS[variant])


@cache
def _font_family() -> str:
    """Load the bundled Chinese chart font.

    Returns:
        The font family name registered with Matplotlib.
    """
    font_manager.fontManager.addfont(_FONT_FILE)
    return font_manager.FontProperties(fname=_FONT_FILE).get_name()


def _count_axes(axes: Axes) -> None:
    """Style and format the shared integer-count axis."""
    axes.spines[["right", "top"]].set_visible(False)
    axes.spines[["left", "bottom"]].set_color("#a2a9b1")
    axes.set_axisbelow(True)
    axes.grid(axis="y", color="#eaecf0")
    axes.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
    axes.tick_params(axis="both", color="#a2a9b1", labelsize=10)


def _quality_history(
    figure: Figure,
    chart: AnnualFigure,
    converter: OpenCC,
) -> None:
    """Draw the annual quality cohorts with an integer stacked total."""
    axes = figure.add_axes((0.11, 0.20, 0.86, 0.55))
    bottom = [0] * len(chart.axis)
    for series in chart.series:
        axes.bar(
            chart.axis,
            series.counts,
            bottom=bottom,
            width=0.76,
            color=series.color,
            edgecolor="white",
            linewidth=0.4,
            label=converter.convert(series.label),
        )
        bottom = [
            base + count
            for base, count in zip(bottom, series.counts, strict=True)
        ]
    limit = max(
        _QUALITY_AXIS_MINIMUM_MAX,
        math.ceil(max(bottom) / _QUALITY_AXIS_STEP) * _QUALITY_AXIS_STEP,
    )
    axes.set_ylim(0, limit)
    tick_stride = max(1, math.ceil(len(chart.axis) / 20))
    axes.set_xticks(chart.axis[::tick_stride])
    axes.tick_params(axis="x", labelrotation=45)
    axes.set_xlabel(converter.convert("年份"), fontsize=11)
    axes.set_ylabel(converter.convert("入选篇数"), fontsize=11)
    axes.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncols=len(chart.series),
        fontsize=11,
        frameon=False,
    )
    _count_axes(axes)


def _dyk_history(
    figure: Figure,
    chart: AnnualFigure,
    converter: OpenCC,
) -> None:
    """Draw cumulative recommendations at their observed dates."""
    axes = figure.add_axes((0.14, 0.17, 0.82, 0.62))
    observed = [dt.date.fromisoformat(str(day)) for day in chart.axis]
    series = chart.series[0]
    axes.fill_between(observed, series.counts, color=series.color)
    axes.plot(observed, series.counts, color="#505ebe", linewidth=1.3)
    axes.margins(x=0.015, y=0.12)
    axes.set_ylim(bottom=0)
    span = observed[-1].year - observed[0].year
    axis_format = "%Y-%m" if span <= _MAX_YEARS_WITH_MONTH_TICKS else "%Y"
    axes.xaxis.set_major_locator(dates.AutoDateLocator(minticks=4, maxticks=7))
    axes.xaxis.set_major_formatter(dates.DateFormatter(axis_format))
    axes.set_xlabel(converter.convert("日期"), fontsize=11)
    axes.set_ylabel(converter.convert("条目数"), fontsize=11)
    axes.annotate(
        f"{series.counts[-1]:,}",
        (observed[-1], series.counts[-1]),
        xytext=(-2, 6),
        textcoords="offset points",
        ha="right",
        fontsize=12,
        color="#354198",
    )
    _count_axes(axes)


def _percentages(counts: tuple[int, ...]) -> tuple[str, ...]:
    """Label slices whose exact share meets the threshold.

    Returns:
        Rounded percentages with blanks for slices below the threshold.
    """
    total = sum(counts)
    return tuple(
        f"{count / total:.1%}"
        if count * 100 >= _LABEL_THRESHOLD * total
        else ""
        for count in counts
    )


def _quality_distribution(
    figure: Figure,
    chart: AnnualFigure,
    converter: OpenCC,
) -> None:
    """Draw the current distribution with exact counts in the legend."""
    counts = tuple(series.counts[0] for series in chart.series)
    percentages = iter(_percentages(counts))
    axes = figure.add_axes((0.022, 0.065, 0.51, 0.75))
    wedges, _, _ = axes.pie(
        counts,
        colors=[series.color for series in chart.series],
        startangle=90,
        counterclock=False,
        autopct=lambda _: next(percentages),
        pctdistance=0.72,
        wedgeprops={"linewidth": 0.55, "edgecolor": "white"},
        textprops={"fontsize": 11, "color": "#202122"},
    )
    figure.legend(
        wedges,
        [
            f"{converter.convert(series.label)}  {count:,}"
            for series, count in zip(chart.series, counts, strict=True)
        ],
        loc="center left",
        bbox_to_anchor=(0.53, 0.435),
        frameon=False,
        fontsize=11,
        handlelength=1.05,
        labelspacing=0.39,
    )


def save_feature_png(chart: AnnualFigure, variant: str, path: Path) -> None:
    """Draw a localized figure and atomically replace its PNG.

    Args:
        chart: Prepared counts, labels, and coverage for one figure.
        variant: Chinese variant of its publication file.
        path: Destination in an existing directory.
    """
    converter = _converter(variant)
    title = converter.convert(chart.title)
    draw = {1: _quality_history, 2: _dyk_history, 3: _quality_distribution}
    temporary = None
    try:
        with (
            rc_context({
                "font.family": _font_family(),
                "text.color": "#202122",
            }),
            NamedTemporaryFile(dir=path.parent, delete=False) as stream,
        ):
            temporary = Path(stream.name)
            figure = Figure(
                figsize=_FIGURE_SIZE[chart.number],
                facecolor="white",
                dpi=200,
            )
            figure.text(0.5, 0.941, title, ha="center", va="top", fontsize=17)
            if chart.data_through:
                figure.text(
                    0.5,
                    0.872,
                    converter.convert(f"数据截至 {chart.data_through}"),
                    ha="center",
                    va="top",
                    fontsize=10,
                    color="#54595d",
                )
            draw[chart.number](figure, chart, converter)
            FigureCanvasAgg(figure).print_png(
                stream,
                metadata={"Title": title},
            )
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _cached_filename(issue: Issue, chart: AnnualFigure, variant: str) -> str:
    """Bind a filename to the chart's saved facts.

    Returns:
        A cache name distinct for each image or rendering contract.
    """
    digest = sha256(encode_json([1, chart])).hexdigest()[:16]
    name = f"Aranami-newsletter-{issue.year}01-{chart.number}-{variant}"
    return f"{name}-{digest}.png"


def _uses_pngs(issue: Issue) -> bool:
    """Identify annual drafts since the published January 2026 issue.

    Returns:
        Whether the issue is eligible for locally rendered PNGs.
    """
    return issue.month == 1 and issue.year >= FIRST_PNG_ISSUE


def prepare_newsletter_charts(runtime: Path, data: Mapping) -> None:
    """Prepare distinct current-year images from saved issues."""
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
                if path.is_file() or path.is_symlink():
                    continue
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                    save_feature_png(chart, variant, path)
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
    """List saved PNGs with the WikiProject publication names.

    Returns:
        Immutable image URLs with editable-issue download filenames.
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
                charts.append({
                    "url": CHART_ROUTE + name,
                    "language": variant,
                    "label": label,
                    "title": _converter(variant).convert(chart.title),
                    "filename": figure_filename(
                        issue.year,
                        chart.number,
                        variant,
                    ),
                })
    return charts


def backfill_saved_charts(runtime: Path) -> None:
    """Prepare PNGs from current and dated annual facts."""
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
