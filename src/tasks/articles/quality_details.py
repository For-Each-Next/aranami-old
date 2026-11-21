"""Collect Article List metadata from the public Wiki Replicas."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING

import polars as pl
from sqlalchemy.exc import SQLAlchemyError

from data.articles import quality_details
from shared.sources.quarry.enwp import english_counterparts
from shared.sources.quarry.revisions import article_edit_years
from shared.sources.quarry.users import project_editor_edit_years

if TYPE_CHECKING:
    from pathlib import Path

    from pywikibot.site import BaseSite

_LOG = logging.getLogger(__name__)


def _due(runtime: Path, scope: str, candidates: pl.DataFrame) -> pl.DataFrame:
    """Prioritize unobserved subjects, then the oldest observations.

    Returns:
        Subjects without a saved observation from the past seven days.
    """
    key = candidates.columns[0]
    checked = (
        quality_details
        .load(runtime, scope)
        .group_by(key)
        .agg(
            pl.col("observed_at").max(),
        )
    )
    keys = (
        ["observed_at", "listed_date", key]
        if scope == "articles"
        else [
            "observed_at",
            key,
        ]
    )
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=7)
    return (
        candidates
        .join(checked, on=key, how="left", validate="1:1")
        .filter(
            pl.col("observed_at").is_null() | (pl.col("observed_at") < cutoff),
        )
        .sort(
            keys,
            descending=[name == "listed_date" for name in keys],
            nulls_last=[name != "observed_at" for name in keys],
        )
    )


def refresh_article_details(
    site: BaseSite,
    runtime: Path,
    articles: pl.DataFrame,
    limit: int,
) -> None:
    """Update a batch of pages, starting with recent assessments."""
    try:
        pages = _due(
            runtime,
            "articles",
            articles.select("page_id", "listed_date"),
        ).head(limit)
        if pages.is_empty():
            return
        ids = pages["page_id"].to_list()
        details = (
            pages
            .select("page_id")
            .join(
                article_edit_years(site, ids),
                on="page_id",
                how="left",
                validate="1:m",
            )
            .join(
                english_counterparts(ids),
                on="page_id",
                how="left",
                validate="m:1",
            )
            .with_columns(pl.col("edits").fill_null(0))
        )
        quality_details.save(
            runtime,
            "articles",
            details,
            dt.datetime.now(dt.UTC),
        )
    except OSError, ValueError, pl.exceptions.PolarsError, SQLAlchemyError:
        _LOG.warning("Article detail observations unavailable.", exc_info=True)


def refresh_editor_history(
    site: BaseSite,
    runtime: Path,
    names: pl.DataFrame,
) -> None:
    """Update project edit histories for registered editors."""
    try:
        due = _due(runtime, "editors", names).head(6).select("name")
        if due.is_empty():
            return
        years = project_editor_edit_years(
            site,
            due["name"].to_list(),
            "电子游戏",
        )
        counts = due.join(
            years,
            on="name",
            how="left",
            validate="1:m",
        ).with_columns(pl.col("edits").fill_null(0))
        quality_details.save(
            runtime,
            "editors",
            counts,
            dt.datetime.now(dt.UTC),
        )
    except OSError, ValueError, pl.exceptions.PolarsError, SQLAlchemyError:
        _LOG.warning("Project edit histories unavailable.", exc_info=True)
