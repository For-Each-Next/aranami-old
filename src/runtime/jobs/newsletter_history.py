"""Collect article recognition history for newsletter preparation."""

from __future__ import annotations

import datetime as dt
import logging

import pywikibot

from data.articles.milestone_store import sync_current_assessments
from data.articles.scope import reconcile_scope
from data.articles.storage import MILESTONES_PATH
from runtime.collection_status import collection_run
from runtime.project_observations import project_cycle
from shared.assessment_profiles import assessment_profile
from shared.identity import configure_pywikibot
from shared.sources.quarry.projects import query_pages_by_wikiproject
from tasks.articles.history import (
    DEFAULT_PATH,
    collect_article_history,
    history_membership,
)
from tasks.articles.milestones import enrich_milestones

_LOGGER = logging.getLogger(__name__)


def run(*, now: dt.datetime | None = None) -> None:
    """Maintain project recognition evidence in an hourly pass.

    Preserve recorded years; idle workers fill missing author credits.
    Newsletter preparation reads the saved evidence separately.

    Args:
        now: UTC source cycle selected for this invocation.
    """
    with (
        collection_run("newsletter-history", trigger="scheduled"),
        project_cycle(now=now),
    ):
        configure_pywikibot()
        site = pywikibot.Site("zh", "wikipedia")
        membership = query_pages_by_wikiproject(site, "电子游戏")
        history_members = history_membership(site, membership)
        reconcile_scope(
            history_members,
            MILESTONES_PATH.parent,
            observed_at=dt.datetime.now(dt.UTC),
        )
        events = collect_article_history(
            site,
            history_members,
            now=dt.datetime.now(dt.UTC),
            path=DEFAULT_PATH,
        )
        enrich_milestones(events, site, max_requests=10)
        sync_current_assessments(
            membership,
            MILESTONES_PATH,
            observed_at=dt.datetime.now(dt.UTC),
            profile=assessment_profile(site.dbName(), "电子游戏"),
        )
        _LOGGER.info(
            "Hourly recognition scan retained %d project events.",
            events.height,
        )
