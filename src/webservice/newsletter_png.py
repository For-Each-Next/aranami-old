"""Draw a Video Games WikiProject newsletter figure as a PNG.

Preparation for a downloaded script:

1. Use Python 3.12 or newer and install the packages used to draw and
   localize the figure:

       python -m pip install matplotlib==3.11.2
       python -m pip install opencc-python-reimplemented==0.1.7

2. Save newsletter-font.otf beside this script. Aranami uses this Noto
   Sans CJK subset for labels in all three editions.

       https://aranami.toolforge.org/newsletter/charts/newsletter-font.otf

   The font's SIL Open Font License is available at:

       https://aranami.toolforge.org/newsletter/charts/newsletter-font.LICENSE

3. Run `python path/to/the-downloaded-script.py`. It reads the included
   dates, counts, and language edition and writes the PNG beside the
   script. The Agg backend works offline without a display server.
"""

from __future__ import annotations

import datetime as dt
import math
import os
from functools import cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from matplotlib import dates, font_manager, rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from opencc import OpenCC

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from data.newsletter.figures import AnnualFigure


_CONVERSIONS = {"zh-cn": "t2s", "zh-tw": "s2twp", "zh-hk": "s2hk"}
FONT_FILE = Path(__file__).with_name("newsletter-font.otf")
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


def localized_title(chart: AnnualFigure, variant: str) -> str:
    """Return the same localized figure title used for the PNG."""
    return _converter(variant).convert(chart.title)


@cache
def _font_family() -> str:
    """Load the bundled Chinese chart font.

    Returns:
        The font family name registered with Matplotlib.
    """
    font_manager.fontManager.addfont(FONT_FILE)
    return font_manager.FontProperties(fname=FONT_FILE).get_name()


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
        f"{series.counts[-1]:,}".replace(",", "\N{THIN SPACE}"),
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
            converter.convert(series.label)
            + "  "
            + f"{count:,}".replace(",", "\N{THIN SPACE}")
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
    title = localized_title(chart, variant)
    draw = {1: _quality_history, 2: _dyk_history, 3: _quality_distribution}
    temporary = None
    try:
        with (
            rc_context({
                "font.family": [_font_family(), "DejaVu Sans"],
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
