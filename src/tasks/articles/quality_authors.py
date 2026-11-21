"""Refresh saved public-edit observations for the article directory."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from data.articles import current_quality, quality_authors
from shared.sources.quarry.users import fetch_user_activity
from tasks.articles.quality_details import refresh_editor_history

if TYPE_CHECKING:
    from pywikibot.site import BaseSite

_LOGGER = logging.getLogger(__name__)


def refresh_quality_author_activity(
    site: BaseSite,
    *,
    runtime: Path = Path(),
) -> None:
    """Refresh due account observations for both all-grade directories.

    Each eligible account is checked once per UTC hour. Missing article
    evidence defers acquisition and failed pulls retain accepted values.

    Args:
        site: Existing Chinese Wikipedia source site.
        runtime: Runtime root containing the saved catalog inputs.
    """
    try:
        _refresh(site, runtime)
    except Exception:
        _LOGGER.warning("Quality-author activity unavailable.", exc_info=True)


def _refresh(site: BaseSite, runtime: Path) -> None:
    """Read only the accounts whose saved observations are due."""
    names = current_quality.author_activity_names(runtime)
    if names.is_empty():
        return
    path = runtime / quality_authors.ACTIVITY_PATH
    hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
    checked = quality_authors.load_activity(path).filter(
        pl.col("observed_at") >= hour,
    )
    due = names.join(checked, on="name", how="anti")
    refresh_editor_history(site, runtime, names)
    if due.is_empty():
        return
    observed = fetch_user_activity(site, due["name"].to_list())
    refreshed = (
        due
        .join(observed, on="name", how="left", validate="1:1")
        .with_columns(pl.lit(dt.datetime.now(dt.UTC)).alias("observed_at"))
        .select(list(quality_authors.ACTIVITY_SCHEMA))
        .cast(quality_authors.ACTIVITY_SCHEMA)
    )
    quality_authors.save_activity(path, refreshed)
