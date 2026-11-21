"""Select the annual newsletter figures and their publication names."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, NamedTuple

import polars as pl

from data.newsletter.grades import QUALITY_GRADES, annual_quality_rows

if TYPE_CHECKING:
    from collections.abc import Mapping

CHART_VARIANTS = {
    "zh-cn": "简体中文",
    "zh-hk": "香港繁體",
    "zh-tw": "臺灣正體",
}
FIRST_PNG_ISSUE = 2027
QUALITY_HISTORY_TITLE = "历年新入选、晋级高品质条目"
DYK_HISTORY_TITLE = "电子游戏专题累计新条目推荐数量"
_QUALITY_HISTORY_SERIES = (
    ("featured", "典范级", "fa"),
    ("a", "甲级", "a"),
    ("GA", "优良级", "ga"),
    ("Bplus", "乙上级", "bplus"),
)


class ChartSeries(NamedTuple):
    """A color and label for one series of observed counts."""

    label: str
    color: str
    counts: tuple[int, ...]


class AnnualFigure(NamedTuple):
    """Numbered image inputs shared by the draft and PNG renderer."""

    number: int
    title: str
    axis: tuple[int | str, ...]
    series: tuple[ChartSeries, ...]
    data_through: str | None


def figure_filename(issue_year: int, number: int, variant: str) -> str:
    """Name one localized figure for the January issue.

    Returns:
        The filename used for both uploads and File2 calls.
    """
    base = f"WPVG Newsletter {issue_year}01 Feature Graph {number}"
    return f"{base} ({variant}).png"


def distribution_title(year: int) -> str:
    """Name the end-of-year assessment distribution.

    Returns:
        The caption for the chart and its wikitext image.
    """
    return f"{year}年年终条目品质概况"


def annual_data_through(
    review: Mapping,
    *,
    data_through: str | None = None,
) -> dt.date | None:
    """Read the inclusive figure date from an override or annual cutoff.

    Returns:
        The last covered date when source evidence supplies one.
    """
    try:
        if data_through is not None:
            return dt.date.fromisoformat(data_through)
        return dt.date.fromisoformat(review["observation_end"]) - dt.timedelta(
            days=1,
        )
    except KeyError, TypeError, ValueError:
        return None


def _quality_history(rows: list[dict], through: str | None) -> AnnualFigure:
    """Combine article and list grades in their published series order.

    Returns:
        Annual counts for each category in the stacked bar chart.
    """
    frame = (
        pl
        .DataFrame(rows)
        .unnest("grades")
        .with_columns(
            (pl.col("FA") + pl.col("FL")).alias("featured"),
            (pl.col("A") + pl.col("AL")).alias("a"),
        )
    )
    return AnnualFigure(
        1,
        QUALITY_HISTORY_TITLE,
        tuple(frame["year"]),
        tuple(
            ChartSeries(label, QUALITY_GRADES[grade][1], tuple(frame[column]))
            for column, label, grade in _QUALITY_HISTORY_SERIES
            if column != "a" or (frame["a"] > 0).any()
        ),
        through,
    )


def annual_figures(review: Mapping, year: int) -> dict[int, AnnualFigure]:
    """Select the available figures for the reviewed year.

    Returns:
        Numbered figures with cutoff dates for partial observations.
    """
    day = annual_data_through(review)
    through = day.isoformat() if day else None
    figures = {}
    if rows := review.get("quality_year_ends"):
        figures[1] = _quality_history(
            rows,
            None if review.get("complete") else through,
        )
    dyk = [
        row
        for row in review.get("dyk_series") or []
        if row["date"][:4] <= str(year)
    ]
    if dyk:
        last = dyk[-1]["date"]
        cumulative = ChartSeries(
            DYK_HISTORY_TITLE,
            "#b4bbff",
            tuple(row["count"] for row in dyk),
        )
        figures[2] = AnnualFigure(
            2,
            DYK_HISTORY_TITLE,
            tuple(row["date"] for row in dyk),
            (cumulative,),
            last
            if not review.get("complete") or last < f"{year}-12-31"
            else None,
        )
    current = next(
        (
            row
            for row in annual_quality_rows(review, year)
            if row["year"] == year
        ),
        None,
    )
    if current is not None:
        figures[3] = AnnualFigure(
            3,
            distribution_title(year),
            (),
            tuple(
                ChartSeries(label, color, (count,))
                for code, (label, color) in QUALITY_GRADES.items()
                if (count := current["counts"].get(code, 0)) > 0
            ),
            through if current["provisional"] else None,
        )
    return figures
