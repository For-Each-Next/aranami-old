"""Retain the annual edit histories used by Article List dialogs."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from uuid import uuid4

import polars as pl

from data.articles.storage import DEFAULT_ROOT
from data.reports import ReportResult, ReportStore

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

_STAMP = pl.Datetime("us", "UTC")
_YEAR_FIELDS = {"year": pl.Int32, "edits": pl.Int64, "observed_at": _STAMP}
_SCHEMAS = {
    "articles": {
        "page_id": pl.Int64,
        **_YEAR_FIELDS,
        "first_edit": _STAMP,
        "last_edit": _STAMP,
        "english_title": pl.String,
        "english_grade": pl.String,
    },
    "editors": {"name": pl.String, **_YEAR_FIELDS},
}
_KEYS = {"articles": "page_id", "editors": "name"}
_MAX_ROWS = 900_000


def _read(store: ReportStore, scope: str) -> pl.DataFrame:
    """Read the selected generation for one history.

    Returns:
        The saved annual rows, or an empty frame before collection.
    """
    bundle = store.read(f"articles/quality-details/{scope}")
    if bundle is None:
        return pl.DataFrame(schema=_SCHEMAS[scope])
    return bundle.tables["years"]


def load(runtime: Path, scope: str) -> pl.DataFrame:
    """Read one of the retained article or editor histories.

    Returns:
        Annual rows, or a typed empty frame before collection.
    """
    return _read(ReportStore(runtime / DEFAULT_ROOT), scope)


def save(
    runtime: Path,
    scope: str,
    pulled: pl.DataFrame,
    at: datetime,
) -> None:
    """Replace only updated histories and keep the latest observations.

    Raises:
        ValueError: Annual counts, identities or timestamps are invalid.
    """
    if pulled.is_empty():
        return
    key = _KEYS[scope]
    updates = (
        pulled
        .with_columns(pl.lit(at).alias("observed_at"))
        .select(list(_SCHEMAS[scope]))
        .cast(_SCHEMAS[scope])
    )
    year = pl.col("year")
    edits = pl.col("edits")
    message = "Invalid Article List edit history."
    if (
        updates.filter(
            pl.col(key).is_null()
            | edits.is_null()
            | (edits < 0)
            | (year.is_null() != (edits == 0))
            | ~year.is_between(1900, at.year),
        ).height
        or updates.n_unique([key, "year"]) != updates.height
    ):
        raise ValueError(message)
    store = ReportStore(runtime / DEFAULT_ROOT)
    report = f"articles/quality-details/{scope}"
    with store.locked(report):
        bundle = store.read(report, locked=True)
        previous = (
            bundle.tables["years"]
            if bundle
            else pl.DataFrame(schema=_SCHEMAS[scope])
        )
        current = (
            pl
            .concat([previous, updates])
            .filter(
                pl.col("observed_at") == pl.col("observed_at").max().over(key),
            )
            .unique([key, "year"], keep="last")
        )
        if current.height > _MAX_ROWS:
            raise ValueError(message)
        store.write(
            report,
            ReportResult(family="quality-details", tables={"years": current}),
            "",
            run_id=uuid4().hex,
            started_at=dt.datetime.now(dt.UTC),
            target={"site": "zhwiki", "title": "Video games edit histories"},
            locked=True,
        )


def presentation(runtime: Path, page_ids: pl.Series) -> dict:
    """Prepare compact annual series for the saved frontend document.

    Returns:
        Article metadata by page ID and annual editor counts by name.
    """
    annual = pl.struct("year", "edits").filter(pl.col("year").is_not_null())
    articles = (
        load(runtime, "articles")
        .join(page_ids.to_frame(), on="page_id", how="semi")
        .sort("year")
        .group_by("page_id")
        .agg(
            pl.col("first_edit").min().dt.to_string("%+").alias("created_at"),
            pl.col("last_edit").max().dt.to_string("%+").alias("latest_at"),
            pl.col("english_title", "english_grade").first(),
            annual.alias("years"),
        )
    )
    editors = (
        load(runtime, "editors")
        .sort("year")
        .group_by("name")
        .agg(annual.alias("years"))
    )
    return {
        "articles": {
            str(row.pop("page_id")): row
            for row in articles.iter_rows(named=True)
        },
        "editors": dict(editors.iter_rows()),
    }
