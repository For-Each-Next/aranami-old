"""Read scoped relationships from indexed replica tables."""

from __future__ import annotations

from itertools import batched
from typing import TYPE_CHECKING

import polars as pl
from sqlalchemy import and_, or_, select, tuple_

from shared.article_query import key_parts
from shared.sources.quarry import Replica, tables

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.sql import ColumnElement, Select

_BATCH_SIZE = 512
_LOOKUP_BATCH_SIZE = 2048
_BATCH_EDGE_LIMIT = 100_000
_PROJECT_LIMIT = 25_000
_TITLE_COLUMNS = {"namespace": pl.Int64, "title": pl.String}
_LOCAL_REDIRECT = or_(
    tables.Redirect.rd_interwiki.is_(None),
    tables.Redirect.rd_interwiki == "",  # ruff: ignore[compare-to-empty-string] - SQL comparison.
)


def _batches[T](  # ruff: ignore[too-many-arguments] - Bind a select and its indexed restriction.
    wiki: str,
    statement: Select,
    column: ColumnElement,
    selected: Iterable[T],
    schema: dict,
    *,
    max_rows: int | None = None,
) -> tuple[pl.DataFrame, set[T]]:
    """Read indexed batches with an optional row budget.

    Returns:
        The rows read and selections whose batches were complete.
    """
    replica = Replica(wiki)
    frames = []
    complete: set[T] = set()
    remaining = max_rows
    size = _LOOKUP_BATCH_SIZE if max_rows is None else _BATCH_SIZE
    for batch in batched(dict.fromkeys(selected), size, strict=False):
        if remaining == 0:
            break
        query = statement.where(column.in_(batch))
        limit = (
            min(remaining, _BATCH_EDGE_LIMIT)
            if remaining is not None
            else None
        )
        if limit is not None:
            query = query.limit(limit + 1)
        frame = replica.query(query, schema_overrides=schema).collect()
        if limit is None or frame.height <= limit:
            complete.update(batch)
        else:
            frame = frame.head(limit)
        frames.append(frame)
        if remaining is not None:
            remaining -= frame.height
    return (
        pl.concat(frames) if frames else pl.DataFrame(schema=schema)
    ), complete


def _key(namespace: str, title: str) -> pl.Expr:
    """Qualify a replica title by namespace.

    Returns:
        An expression producing the title key.
    """
    return pl.concat_str(namespace, title, separator=":")


def titles(wiki: str, keys: Iterable[str]) -> pl.DataFrame:
    """Read exact page IDs and redirect targets.

    Returns:
        Requested keys with nullable page IDs and redirect targets.
    """
    selected = list(dict.fromkeys(keys))
    page = tables.Page
    redirect = tables.Redirect
    statement = select(
        page.page_namespace.label("namespace"),
        page.page_title.label("title"),
        page.page_id,
        redirect.rd_namespace.label("redirect_ns"),
        redirect.rd_title.label("redirect_title"),
    ).outerjoin(
        redirect,
        and_(redirect.rd_from == page.page_id, _LOCAL_REDIRECT),
    )
    frame, _ = _batches(
        wiki,
        statement,
        tuple_(page.page_namespace, page.page_title),
        (key_parts(key) for key in selected),
        {
            **_TITLE_COLUMNS,
            "page_id": pl.Int64,
            "redirect_ns": pl.Int64,
            "redirect_title": pl.String,
        },
    )
    observed = frame.select(
        _key("namespace", "title").alias("key"),
        "page_id",
        _key("redirect_ns", "redirect_title").alias("redirect"),
    )
    return pl.DataFrame(
        {"key": selected},
        schema={"key": pl.String},
    ).join(
        observed,
        on="key",
        how="left",
        validate="1:1",
        maintain_order="left",
    )


def subject_pages(wiki: str, ids: Iterable[int]) -> pl.DataFrame:
    """Read nonredirect main pages and their talk identities.

    Returns:
        Subject IDs, database titles and optional talk-page IDs.
    """
    page = tables.Page.__table__
    talk = page.alias("article_query_talk")
    statement = (
        select(
            page.c.page_id,
            page.c.page_title.label("title"),
            talk.c.page_id.label("talk_id"),
        )
        .select_from(page)
        .outerjoin(
            talk,
            and_(
                talk.c.page_namespace == 1,
                talk.c.page_title == page.c.page_title,
            ),
        )
        .where(page.c.page_namespace == 0, page.c.page_is_redirect == 0)
    )
    frame, _ = _batches(
        wiki,
        statement,
        page.c.page_id,
        ids,
        {"page_id": pl.Int64, "title": pl.String, "talk_id": pl.Int64},
    )
    return frame


def project_names(wiki: str) -> pl.DataFrame:
    """Check the complete WikiProject name inventory.

    Returns:
        A table of unique exact project names.

    Raises:
        ValueError: The inventory exceeds its collection bound.
    """
    project = tables.PageAssessmentsProjects
    frame = (
        Replica(wiki)
        .query(
            select(project.pap_project_title.label("project")).limit(
                _PROJECT_LIMIT + 1,
            ),
            schema_overrides={"project": pl.String},
        )
        .collect()
    )
    if frame.height > _PROJECT_LIMIT:
        message = "The WikiProject name inventory exceeds its bound."
        raise ValueError(message)
    return frame.unique("project")


def assessments(
    wiki: str,
    ids: Iterable[int],
    max_rows: int,
) -> tuple[pl.DataFrame, set[int]]:
    """Read class and importance from project assessments.

    Returns:
        Per-project rows and subject IDs with fully read batches.
    """
    assessment = tables.PageAssessments
    project = tables.PageAssessmentsProjects
    statement = select(
        assessment.pa_page_id.label("page_id"),
        project.pap_project_title.label("project"),
        assessment.pa_class.label("grade"),
        assessment.pa_importance.label("importance"),
    ).join(project, project.pap_project_id == assessment.pa_project_id)
    return _batches(
        wiki,
        statement,
        assessment.pa_page_id,
        ids,
        {
            "page_id": pl.Int64,
            "project": pl.String,
            "grade": pl.String,
            "importance": pl.String,
        },
        max_rows=max_rows,
    )


def edges(
    wiki: str,
    kind: str,
    ids: Iterable[int],
    max_rows: int,
) -> tuple[pl.DataFrame, set[int]]:
    """Read outgoing category, template or ordinary page links.

    Returns:
        Relation rows and their fully observed source IDs.
    """
    source, link = {
        "cat": (
            tables.Categorylinks.cl_from,
            tables.Categorylinks.cl_target_id,
        ),
        "tl": (
            tables.Templatelinks.tl_from,
            tables.Templatelinks.tl_target_id,
        ),
        "link": (tables.Pagelinks.pl_from, tables.Pagelinks.pl_target_id),
    }[kind]
    target = tables.Linktarget
    statement = select(
        source.label("page_id"),
        target.lt_namespace.label("namespace"),
        target.lt_title.label("title"),
    ).join(target, target.lt_id == link)
    frame, complete = _batches(
        wiki,
        statement,
        source,
        ids,
        {"page_id": pl.Int64, **_TITLE_COLUMNS},
        max_rows=max_rows,
    )
    return frame.select(
        "page_id",
        _key("namespace", "title").alias("key"),
    ), complete


def backlinks(
    wiki: str,
    keys: Iterable[str],
    max_rows: int,
) -> tuple[pl.DataFrame, set[str]]:
    """Read incoming links through the target index.

    Returns:
        Source and target keys, and fully observed target keys.
    """
    target, links, page = tables.Linktarget, tables.Pagelinks, tables.Page
    statement = (
        select(
            target.lt_namespace.label("target_ns"),
            target.lt_title.label("target_title"),
            page.page_namespace.label("namespace"),
            page.page_title.label("title"),
        )
        .select_from(target)
        .join(links, links.pl_target_id == target.lt_id)
        .join(page, page.page_id == links.pl_from)
    )
    frame, complete = _batches(
        wiki,
        statement,
        tuple_(target.lt_namespace, target.lt_title),
        (key_parts(key) for key in keys),
        {**_TITLE_COLUMNS, "target_ns": pl.Int64, "target_title": pl.String},
        max_rows=max_rows,
    )
    return (
        frame.select(
            _key("target_ns", "target_title").alias("target"),
            _key("namespace", "title").alias("key"),
        ),
        {f"{ns}:{title}" for ns, title in complete},
    )


def incoming_redirects(
    wiki: str,
    keys: Iterable[str],
    max_rows: int,
) -> tuple[pl.DataFrame, set[str]]:
    """Read local aliases through the redirect target index.

    Returns:
        Redirect pairs and fully observed destination keys.
    """
    page, redirect = tables.Page, tables.Redirect
    statement = (
        select(
            redirect.rd_namespace.label("target_ns"),
            redirect.rd_title.label("target_title"),
            page.page_namespace.label("namespace"),
            page.page_title.label("title"),
        )
        .select_from(redirect)
        .join(page, page.page_id == redirect.rd_from)
        .where(_LOCAL_REDIRECT)
    )
    frame, complete = _batches(
        wiki,
        statement,
        tuple_(redirect.rd_namespace, redirect.rd_title),
        (key_parts(key) for key in keys),
        {**_TITLE_COLUMNS, "target_ns": pl.Int64, "target_title": pl.String},
        max_rows=max_rows,
    )
    return (
        frame.select(
            _key("target_ns", "target_title").alias("target"),
            _key("namespace", "title").alias("key"),
        ),
        {f"{ns}:{title}" for ns, title in complete},
    )
