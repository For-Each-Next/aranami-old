"""Serve paged article and chart views from saved generations."""

from __future__ import annotations

import json
import unicodedata
from base64 import b64decode
from binascii import Error as Base64Error
from functools import lru_cache
from operator import itemgetter
from time import monotonic
from typing import TYPE_CHECKING

import polars as pl
import regex

from data.articles import quality_pages
from data.articles.quality_selection import quartiles
from webservice.presentation import Interface, display_title
from webservice.quality_analysis import (
    ARTICLE_PAGE_SIZE,
    ARTICLE_PAGE_SIZES,
    catalog_article,
    contributor_names,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_VIEWS = {"articles", "chart", "coverage", "summary"}
_FIELD_TYPES = {
    **dict.fromkeys(
        (
            "view",
            "search",
            "author",
            "role",
            "grade",
            "importance",
            "group",
            "value",
        ),
        str,
    ),
    **dict.fromkeys(("unknown", "regex", "descending", "measured"), bool),
    **dict.fromkeys(("first", "last", "page", "size", "column", "year"), int),
    "cells": list,
}
_FIRST_YEAR = 2009
_MAX_SEARCH = 200
_MAX_PAGE = 30_000
_COLUMNS = (
    "",
    "title",
    "grade",
    "importance",
    "listed_date",
    "authors",
    "prose_characters",
    "source_bytes",
)
_DENSITY = pl.List(pl.Struct({"position": pl.Float64, "density": pl.Float64}))


class DirectorySearchError(ValueError):
    """Reject an invalid or excessively expensive regular expression."""


@lru_cache(maxsize=1)
def _snapshot(path: Path, name: str, _identity: tuple) -> dict:
    """Reuse one decoded directory until its saved resource changes.

    Args:
        path: Selected, locale-specific quality preset.
        name: Exact directory named by the page.
        _identity: File identity used as part of the cache key.

    Returns:
        Private, validated saved data and reusable search lookups.

    Raises:
        LookupError: The requested generation is no longer available.
    """
    content = quality_pages.read_resource(path, name)
    if content is None:
        message = "The article directory has expired."
        raise LookupError(message)
    return {"data": json.loads(content), "roles": {}}


def _decode(encoded: str) -> dict:
    """Decode the compact, bounded GET query without accepting aliases.

    Returns:
        The validated shape of the request before cohort validation.

    Raises:
        ValueError: The query is malformed or exceeds supported bounds.
    """
    try:
        value = json.loads(
            b64decode(
                encoded + "=" * (-len(encoded) % 4),
                altchars=b"-_",
                validate=True,
            ),
        )
    except (Base64Error, RecursionError) as error:
        message = "Invalid directory query encoding."
        raise ValueError(message) from error
    if not isinstance(value, dict) or any(
        type(item) is not _FIELD_TYPES.get(key) for key, item in value.items()
    ):
        message = "Invalid directory query fields."
        raise ValueError(message)
    if (
        value.get("view") not in _VIEWS
        or any(
            len(value.get(key, "")) > _MAX_SEARCH
            for key in ("search", "author")
        )
        or value.get("role", "main") not in {"main", "significant"}
    ):
        message = "Invalid directory search controls."
        raise ValueError(message)
    if (
        not 1 <= value.get("page", 1) <= _MAX_PAGE
        or value.get("size", ARTICLE_PAGE_SIZE) not in ARTICLE_PAGE_SIZES
        or not 1 <= value.get("column", 4) < len(_COLUMNS)
    ):
        message = "Invalid article directory controls."
        raise ValueError(message)
    return value


def _selection(query: dict, saved: dict) -> set[str]:
    """Check requested cells and inclusive years against the grid.

    Returns:
        The exact selected grade/importance pairs.

    Raises:
        ValueError: The grade, importance or year is outside the grid.
    """
    allowed = {
        f"{grade}:{level}"
        for grade in saved["grades"]
        for level in saved["importance"]
    }
    cells = query.get("cells")
    if (
        len(cells or []) > len(allowed)
        or not all(
            isinstance(cell, str) and cell in allowed for cell in (cells or [])
        )
        or not _FIRST_YEAR
        <= query.get("first", 0)
        <= query.get("last", 0)
        <= saved["last_year"]
        or query.get("grade", "") not in {"", *saved["grades"]}
        or query.get("importance", "") not in {"", *saved["importance"]}
    ):
        message = "Selection is outside the saved directory."
        raise ValueError(message)
    return set(cells or [])


def _year_matches(year: int | None, query: dict) -> bool:
    """Test a saved year against the requested range.

    Returns:
        Whether the year or the unknown-date setting matches.
    """
    return (
        query.get("unknown", False)
        if year is None
        else query["first"] <= year <= query["last"]
    )


def _record_year(row: dict) -> int | None:
    """Return the saved listing year, preserving missing dates."""
    date = row.get("listed_date")
    return int(date[:4]) if date else None


def _importance(row: dict) -> str:
    """Return the directory's explicit unknown-importance category."""
    return row.get("importance") or "Unknown"


def _cohort(saved: dict, query: dict, cells: set[str]) -> list[dict]:
    """Select rows for the requested grade, importance and year.

    Returns:
        Saved rows in source order for stable table sorting.
    """
    return [
        row
        for row in saved["articles"]
        if f"{row['grade']}:{_importance(row)}" in cells
        and _year_matches(_record_year(row), query)
    ]


def _has_authorship(row: dict) -> bool:
    """Return whether the row has observed authorship proof."""
    return bool(
        (row.get("authorship") or {}).get(
            "available",
            row.get("authorship_available"),
        ),
    )


@lru_cache(maxsize=32_768)
def _folded(value: str) -> str:
    """Return the normalized text used by literal search."""
    return display_title(
        unicodedata.normalize("NFKC", value),
        "zh-hans",
    ).lower()


def _matcher(
    text: str,
    *,
    regular: bool,
    whole: bool = False,
) -> Callable[[str], bool]:
    """Build a literal or time-bounded match for one query field.

    Returns:
        A match predicate with a finite regex budget.

    Raises:
        DirectorySearchError: The expression is invalid or too slow.
    """
    if not regular or not text:
        needle = _folded(text)
        if whole:
            return lambda value: _folded(value) == needle
        return lambda value: needle in _folded(value)
    try:
        pattern = regex.compile(text, regex.IGNORECASE | regex.VERSION0)
    except regex.error as error:
        message = "Invalid directory regular expression."
        raise DirectorySearchError(message) from error
    remaining = 0.25

    def matches(value: str) -> bool:
        nonlocal remaining
        started = monotonic()
        try:
            return bool(pattern.search(value, timeout=remaining))
        except TimeoutError as error:
            message = "Directory regular expression timed out."
            raise DirectorySearchError(message) from error
        finally:
            remaining = max(0.0, remaining - (monotonic() - started))

    return matches


def _role_names(record: dict, row: dict, interface: Interface) -> dict:
    """Return cached contributor names for the given article."""
    roles = record["roles"]
    key = (interface.locale, row["page_id"])
    if key not in roles:
        roles[key] = contributor_names(row, interface)
    return roles[key]


def _article_filter(
    rows: list[dict],
    record: dict,
    query: dict,
    interface: Interface,
) -> tuple[list[dict], list[str]]:
    """Filter the whole cohort before slicing one directory page.

    Returns:
        Matching articles and at most twenty contributor suggestions.
    """
    search = query.get("search", "").strip()
    author = query.get("author", "").strip()
    role = query.get("role", "main")
    title_matches = _matcher(search, regular=query.get("regex", False))
    name_matches = _matcher(
        author,
        regular=query.get("regex", False),
        whole=True,
    )
    author_prefix = _folded(author)
    grade, importance = query.get("grade"), query.get("importance")
    suggestions = set()
    filtered = []
    for row in rows:
        if author:
            names = _role_names(record, row, interface)
            labels = names["labels" if role == "main" else "significant"]
            suggestions.update(
                name for name in labels if author_prefix in _folded(name)
            )
            if not any(name_matches(name) for name in [*names[role], *labels]):
                continue
        if (grade and row["grade"] != grade) or (
            importance and _importance(row) != importance
        ):
            continue
        if search and not (
            title_matches(row["title"])
            or title_matches(_display_title(row, interface))
        ):
            continue
        filtered.append(row)
    return filtered, sorted(suggestions, key=_folded)[:20]


def _display_title(row: dict, interface: Interface) -> str:
    """Return the localized title used in the result row."""
    return display_title(row["title"].replace("_", " "), interface.locale)


def _sort_articles(
    rows: list[dict],
    record: dict,
    query: dict,
    interface: Interface,
) -> list[dict]:
    """Sort saved values stably, keeping missing observations last.

    Returns:
        The requested article order before pagination.
    """
    key = _COLUMNS[query.get("column", 4)]
    saved = record["data"]
    keys = {
        "title": lambda row: _display_title(row, interface).casefold(),
        "grade": lambda row: saved["grades"].index(row["grade"]),
        "importance": lambda row: saved["importance"].index(_importance(row)),
        "authors": lambda row: (
            ", ".join(
                _role_names(record, row, interface)["labels"],
            ).casefold()
            or None
        ),
    }
    extract = keys.get(key, lambda row: row.get(key))
    observed, missing = [], []
    for row in rows:
        value = extract(row)
        if value is None:
            missing.append(row)
        else:
            observed.append((value, row))
    observed.sort(
        key=itemgetter(0),
        reverse=query.get("descending", True),
    )
    return [row for _, row in observed] + missing


def _chart_articles(rows: list[dict], query: dict, saved: dict) -> list[dict]:
    """Choose the chart mark independently of directory-local search.

    Returns:
        Entries for the selected chart category, year and measurement.

    Raises:
        ValueError: The chart category is unknown.
    """
    group, value = query.get("group"), query.get("value")
    options = {"grade": saved["grades"], "importance": saved["importance"]}
    if value not in options.get(group, []):
        message = "Unknown chart group."
        raise ValueError(message)
    year = query.get("year")
    return [
        row
        for row in rows
        if (row["grade"] if group == "grade" else _importance(row)) == value
        and (year is None or _record_year(row) == year)
        and (
            not query.get("measured")
            or row.get("prose_characters") is not None
        )
    ]


def _page(rows: list, query: dict) -> dict:
    """Return one valid result page and the total row count."""
    size = query.get("size", ARTICLE_PAGE_SIZE)
    page = min(query.get("page", 1), max(1, (len(rows) + size - 1) // size))
    start = (page - 1) * size
    return {
        "rows": rows[start : start + size],
        "page": page,
        "total": len(rows),
    }


def _coverage(
    saved: dict,
    cohort: list[dict],
    query: dict,
    chosen: set[str],
) -> dict:
    """Read one page of missing evidence or source comparison.

    Returns:
        The bounded evidence list and comparison availability.

    Raises:
        ValueError: The coverage category is unknown.
    """
    kind = query.get("value")
    comparison = saved["comparison"] or {}
    if kind == "total":
        grades = {cell.split(":", 1)[0] for cell in chosen}
        rows = [
            row
            for row in comparison.get("rows", [])
            if row["pageassessments_grade"] in grades
            or grades.intersection(row["category_grades"])
        ]
        return {
            **_page(rows, query),
            "available": bool(comparison.get("available")),
        }
    acquired = {
        "authorship": _has_authorship,
        "dates": lambda row: bool(row.get("listed_date")),
        "length": lambda row: row.get("prose_characters") is not None,
    }.get(kind)
    if acquired is None:
        message = "Unknown quality coverage category."
        raise ValueError(message)
    result = _page([row for row in cohort if not acquired(row)], query)
    result["rows"] = [{"title": row["title"]} for row in result["rows"]]
    return result


def _violin_groups(cells: list[dict], query: dict) -> dict:
    """Summarize saved histograms and densities per plotted category.

    Returns:
        The rendered violin inputs without per-cell samples.
    """
    summary = {"grade": {}, "importance": {}}
    if not cells:
        return summary
    stats = quartiles(
        cells,
        list({cell["grade"] for cell in cells}),
        query["last"],
    )
    frame = pl.DataFrame(
        cells,
        schema={
            "grade": pl.String,
            "importance": pl.String,
            "density": _DENSITY,
        },
    )
    for dimension in summary:
        points = (
            frame
            .select(dimension, "density")
            .explode("density")
            .unnest("density")
            .drop_nulls("position")
            .group_by(dimension, "position")
            .agg(pl.col("density").sum())
            .with_columns(
                (
                    pl.col("density") / pl.col("density").max().over(dimension)
                ).fill_nan(0),
            )
            .sort(dimension, "position")
            .group_by(dimension, maintain_order=True)
            .agg(pl.concat_list("position", "density").alias("points"))
        )
        density = dict(points.iter_rows())
        summary[dimension] = {
            item[dimension]: {
                "minimum": item["minimum"],
                "maximum": item["maximum"],
                "mean": item["mean"],
                "quartiles": [item["p25"], item["p75"]],
                "quantiles": [None, None, item["p50"]],
                "density": density.get(item[dimension], []),
            }
            for item in stats
            if item["group"] == dimension
        }
    return summary


def _summary(
    saved: dict,
    cohort: list[dict],
    query: dict,
    chosen: set[str],
) -> dict:
    """Return only figure counts, plotted summaries and author totals.

    Returns:
        Shared graph and coverage figures for the confirmed cohort.
    """
    available_cells = [
        cell
        for cell in saved["cells"]
        if f"{cell['grade']}:{cell['importance']}" in chosen
    ]
    cells = [
        cell for cell in available_cells if _year_matches(cell["year"], query)
    ]
    ids = {row["page_id"] for row in cohort}
    return {
        "cells": [
            {
                key: cell[key]
                for key in ("grade", "importance", "year", "pages", "measured")
            }
            for cell in cells
        ],
        "lengths": _violin_groups(cells, query),
        "undated": sum(
            cell["pages"] for cell in available_cells if cell["year"] is None
        ),
        "author_counts": {
            name: len(ids.intersection(pages))
            for name, pages in saved["authors"].items()
        },
        "coverage": {
            "total": len(cohort),
            "authorship": sum(_has_authorship(row) for row in cohort),
            "dates": sum(bool(row.get("listed_date")) for row in cohort),
            "length": sum(
                row.get("prose_characters") is not None for row in cohort
            ),
        },
    }


def read_directory(path: Path, name: str, locale: str, encoded: str) -> dict:
    """Read one directory page or figure summary without acquiring data.

    Returns:
        A bounded result for the immutable saved generation.
    """
    query = _decode(encoded)
    record = _snapshot(path, name, quality_pages.identity(path))
    saved = record["data"]
    cells = _selection(query, saved)
    cohort = _cohort(saved, query, cells)
    view = query["view"]
    if view == "summary":
        return _summary(saved, cohort, query, cells)
    if view == "coverage":
        return _coverage(saved, cohort, query, cells)
    interface = Interface(locale)
    if view == "chart":
        filtered = _chart_articles(cohort, query, saved)
        suggestions = []
    else:
        filtered, suggestions = _article_filter(
            cohort,
            record,
            query,
            interface,
        )
    page = _page(_sort_articles(filtered, record, query, interface), query)
    page["rows"] = [
        catalog_article(row, interface, include_authorship=view != "chart")
        for row in page["rows"]
    ]
    return {**page, "cohort": len(cohort), "suggestions": suggestions}
