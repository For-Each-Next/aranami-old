"""Run Article List query collection in its dedicated job."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
lazy import pywikibot

from data.articles import current_assessments, query_index
from data.caching.article_query_checks import TitleChecks
from runtime.observability.collection_status import collection_run
from shared.article_query import PROJECTS, title_key, title_label
from shared.identity import configure_pywikibot
from shared.sources.wiki import title_variant_mappings
from tasks.articles.article_query import (
    REDIRECT_DEPTH,
    partitions,
    script_alternatives,
    subjects,
    title_facts,
)

if TYPE_CHECKING:
    from data.caching.article_query_checks import CheckKey, TitleCheck

_LOGGER = logging.getLogger(__name__)


def _mediawiki(keys: list[str]) -> dict[str, str]:
    """Ask MediaWiki for Chinese variants unresolved by indexed SQL.

    Returns:
        Original keys and their alternatives for replica verification.
    """
    labels = {title_label(key): key for key in keys}
    try:
        configure_pywikibot()
        site = pywikibot.Site("zh", "wikipedia")
        return {
            labels[entered]: title_key("zh", "link", target)
            for entered, target in title_variant_mappings(site, labels).items()
        }
    except Exception:
        _LOGGER.exception("Chinese title variant lookup failed.")
        return {}


def _lookup(site: str, keys: list[str]) -> dict[CheckKey, TitleCheck]:
    """Resolve one queued batch using replicas and Chinese conversion.

    Returns:
        Confirmed title facts and alternatives for each submitted key.
    """
    alternatives = {
        key: list(script_alternatives(key)) if site == "zh" else []
        for key in keys
    }
    wiki = f"{site}wiki"
    targets = [target for group in alternatives.values() for target in group]
    records = {
        key: (page_id, redirect)
        for key, page_id, redirect in title_facts(
            wiki,
            [*keys, *targets],
        ).iter_rows()
    }
    unresolved = [
        key
        for key in keys
        if records[key][0] is None
        and not any(records[target][0] for target in alternatives[key])
    ]
    if site == "zh" and unresolved:
        converted = _mediawiki(unresolved)
        records.update({
            key: (page_id, redirect)
            for key, page_id, redirect in title_facts(
                wiki,
                converted.values(),
            ).iter_rows()
        })
        for key, target in converted.items():
            if target not in alternatives[key]:
                alternatives[key].append(target)
    ready = {}
    for key in keys:
        candidates = [
            target
            for target in alternatives[key]
            if records[key][0] is None and records[target][0] is not None
        ]
        chain = {}
        for start in (key, *candidates):
            target = start
            for _ in range(REDIRECT_DEPTH + 1):
                if target not in records or target in chain:
                    break
                chain[target] = records[target]
                if records[target][1] is None:
                    break
                target = records[target][1]
        ready[site, key] = {"titles": chain, "variants": candidates}
    return ready


def _check_titles(runtime: Path) -> None:
    """Complete queued checks before loading the relation graph."""
    checks = TitleChecks.from_environment(runtime)
    if checks is None:
        return
    pending = checks.pending()
    for site in PROJECTS:
        keys = [key for candidate, key in pending if candidate == site]
        if keys:
            checks.complete(_lookup(site, keys))


def run() -> None:
    """Refresh saved observations under the dedicated job lease.

    Raises:
        LookupError: The Chinese article cohort is unavailable.
    """
    runtime = Path.cwd()
    with collection_run("web-query", trigger="scheduled"):
        _check_titles(runtime)
        members = current_assessments.load(
            runtime / current_assessments.DEFAULT_PATH,
        ).filter(
            (pl.col("page_namespace") == 0)
            & (pl.col("page_is_redirect") == 0),
        )
        if members.is_empty():
            message = "No saved Chinese article membership is available."
            raise LookupError(message)
        observed_at = dt.datetime.now(dt.UTC)
        scopes = subjects(members["page_id"].to_list())
        query_index.publish(runtime, observed_at, partitions(scopes))
