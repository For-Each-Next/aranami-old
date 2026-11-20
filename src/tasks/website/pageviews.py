"""Find Chinese video-game project pages in Wikimedia's daily top list.

The official all-access endpoint covers at most the site's top 1,000
pages. Filter that observed list by current project membership instead
of requesting every article or combining redirect counts. Search only
the previous seven completed UTC dates when daily data is unavailable.
Site ranks follow Topviews' default article-only numbering, excluding
namespace pages, the main page and its short title, and its configured
global false positive. Raw API ranks remain sorting tie breakers.

The response contract was checked against the official Analytics API
project-metrics documentation and the Chinese daily response for
17 October 2025. Its project field is ``zh.wikipedia``; request URLs use
``zh.wikipedia.org``.
"""

# Public API docs include propagated source-validation errors.
# ruff: file-ignore[docstring-extraneous-exception]

from __future__ import annotations

import datetime as dt
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.error import HTTPError

import polars as pl

from shared.sources.pageviews import (
    article_rank_filter,
    fetch_top_observation,
    top_list_url,
)
from shared.support.titles import page_title, page_url

if TYPE_CHECKING:
    from pywikibot.site import BaseSite

_PROJECT = "zh.wikipedia.org"
_ITEM_LIMIT = 12
_LOOKBACK_DAYS = 7


def _period(day: dt.date) -> tuple[str, str, str]:
    """Return the API selectors for a completed UTC date."""
    return day.strftime("%Y"), day.strftime("%m"), day.strftime("%d")


def _request(day: dt.date) -> pl.DataFrame | None:
    """Load a shared top list, skipping only absent daily observations.

    Returns:
        Articles with raw ranks, or none if the date is absent.

    Raises:
        HTTPError: An HTTP error other than 404 prevented collection.
    """
    try:
        observation = fetch_top_observation(_PROJECT, _period(day))
    except HTTPError as error:
        if error.code != HTTPStatus.NOT_FOUND:
            raise
        return None
    if observation is None:
        return None
    return observation.articles.rename({"source_rank": "_source_rank"})


def _article_ranks(observed: pl.DataFrame, site: BaseSite) -> pl.DataFrame:
    """Number the complete daily article list using Topviews' defaults.

    Use shared site metadata without resolving or fetching each title.
    Preserve colon-bearing titles whose prefix is not a namespace.
    Topviews also excludes the namespace-stripped main-page title, such
    as Chinese Wikipedia's ``首页`` redirect.

    Args:
        observed: Validated daily observations retaining raw API ranks.
        site: Chinese Wikipedia with its current namespace metadata.

    Returns:
        Retained observations with contiguous article-only site ranks.
    """
    namespaces = (
        namespace["*"] for namespace in site.siteinfo["namespaces"].values()
    )
    mainpage = site.siteinfo["mainpage"].replace("_", " ")
    return (
        observed
        .filter(article_rank_filter(pl.col("title"), namespaces, mainpage))
        .sort("_source_rank", maintain_order=True)
        .with_row_index("site_rank", offset=1)
    )


def collect_pageviews(
    today: dt.date,
    members: set[str],
    *,
    site: BaseSite,
) -> dict[str, object]:
    """Rank project members in the latest available daily top list.

    Start with yesterday and inspect at most seven completed UTC dates.
    Only missing daily observations permit trying an older date. A valid
    empty article list or no matching project members remains a measured
    empty result, whereas exhausted missing dates raise an error.

    Args:
        today: Current UTC date excluded from daily measurements.
        members: Current Chinese project article titles.
        site: Chinese Wikipedia supplying shared namespace metadata.

    Returns:
        Date, coverage, source URL, and up to twelve ranked articles.
        Ranks identify this filtered list; ``site_rank`` follows the
        complete article-only list before project filtering, matching
        Topviews' defaults. Views keep their original counts.

    Raises:
        RuntimeError: No daily observation exists in the bounded window.
        TypeError: Source objects or lists have invalid types.
        ValueError: A source response violates the verified contract.
    """
    membership = pl.DataFrame(
        {"title": [page_title(site, title) for title in members]},
        schema={"title": pl.String},
    ).unique()
    for offset in range(1, _LOOKBACK_DAYS + 1):
        day = today - dt.timedelta(days=offset)
        observed = _request(day)
        if observed is None:
            continue
        observed = observed.with_columns(
            pl.Series(
                "title",
                [page_title(site, title) for title in observed["title"]],
                dtype=pl.String,
            ),
        )
        items = (
            _article_ranks(observed, site)
            .join(membership, on="title", how="semi")
            .sort(
                ["views", "_source_rank", "title"],
                descending=[True, False, False],
            )
            .head(_ITEM_LIMIT)
            .with_row_index("rank", offset=1)
            .select(
                "title",
                "views",
                "rank",
                "site_rank",
            )
        )
        return {
            "date": day.isoformat(),
            "limit": _ITEM_LIMIT,
            "scope": "site_top_1000",
            "items": [
                {**item, "url": page_url(site, item["title"])}
                for item in items.to_dicts()
            ],
            "source_url": top_list_url(_PROJECT, _period(day)),
        }
    message = "No daily pageviews observation exists in the past seven dates."
    raise RuntimeError(message)
