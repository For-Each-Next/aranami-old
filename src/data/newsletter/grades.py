"""Describe newsletter grade series and stable annual chart identities.

Use shared assessment metadata for labels and normalization. These
inventories select grades and colors for persisted newsletter charts.
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from shared.assessment_profiles import assessment_profile
from shared.support.files import encode_json

if TYPE_CHECKING:
    from collections.abc import Mapping

_ASSESSMENTS = assessment_profile("zhwiki", "电子游戏")
QUALITY_HISTORY_GRADES = ("FA", "FL", "A", "AL", "GA", "Bplus")
NEW_PAGE_GRADES = frozenset(
    label.code
    for label in _ASSESSMENTS.labels("class")
    if label.order is not None or label.code == "Unknown"
)
# Select persisted series; grade labels and colors come from metadata.
_QUALITY_SERIES = (
    "FA",
    "FL",
    "A",
    "AL",
    "GA",
    "Bplus",
    "B",
    "BL",
    "C",
    "CL",
    "Start",
    "List",
    "Stub",
    "SL",
    "Unassessed",
)
QUALITY_GRADES = {
    code.lower(): (
        _ASSESSMENTS.resolve(code, "class").long_name,
        _ASSESSMENTS.color(code, "class", variant="newsletter_annual"),
    )
    for code in _QUALITY_SERIES
}
CHART_VARIANTS = {
    "zh-hans": "简体中文",
    "zh-tw": "臺灣正體",
    "zh-hk": "香港繁體",
}


def annual_quality_rows(review: Mapping, year: int) -> list[dict]:
    """Select two annual distributions with positive totals.

    Returns:
        The saved distributions eligible for both forms of chart output.
    """
    return [
        row
        for row in review.get("quality_statistics") or []
        if row["year"] in {year - 1, year} and any(row["counts"].values())
    ]


def quality_chart_filename(row: Mapping, variant: str) -> str:
    """Name one annual chart from its saved counts and drawing contract.

    Returns:
        An immutable name for the draft and download route.
    """
    digest = sha256(
        encode_json({
            "revision": 1,
            "counts": row["counts"],
            "grades": QUALITY_GRADES,
        }),
    ).hexdigest()[:16]
    return f"Aranami-quality-{row['year']}-{variant}-{digest}.svg"
