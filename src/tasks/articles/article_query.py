"""Prepare bounded relation and title indexes for the Article List."""

from __future__ import annotations

from functools import lru_cache
from itertools import batched
from typing import TYPE_CHECKING

import polars as pl
from opencc import OpenCC

from data.articles.query_index import MAX_EDGE_ROWS, MAX_TITLE_ROWS, SCHEMAS
from shared.article_query import MAX_CATEGORY_DEPTH, key_parts
from shared.config import ARTICLE_GRADE_CATEGORIES
from shared.sources.quarry import article_query as replica
from shared.sources.quarry.enwp import english_sitelinks

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

REDIRECT_DEPTH = 8
_REDIRECT_ROWS = 80_000
_ANCESTOR_ROWS = 150_000
_VARIANT_TITLES = 45_000
_SITELINK_BATCH = 1000
_EN_CATEGORY = "14:B-Class_video_game_articles"


@lru_cache(maxsize=2)
def _converter(direction: str) -> OpenCC:
    """Reuse the worker's two Chinese script dictionaries.

    Returns:
        The converter for the selected direction.
    """
    return OpenCC(direction)


def script_alternatives(key: str) -> tuple[str, ...]:
    """Generate Chinese script alternatives for an exact title.

    Returns:
        Unique candidates in the same namespace as the input.
    """
    namespace, title = key_parts(key)
    return tuple(
        dict.fromkeys(
            f"{namespace}:{converted}"
            for direction in ("t2s", "s2t")
            if (converted := _converter(direction).convert(title)) != title
        ),
    )


def title_facts(wiki: str, keys: Iterable[str]) -> pl.DataFrame:
    """Read exact titles and follow their local redirect chains.

    Returns:
        Title facts for the submitted keys and reached destinations.
    """
    frame = replica.titles(wiki, keys)
    frontier = frame
    for _ in range(REDIRECT_DEPTH):
        unseen = (
            frontier
            .select(pl.col("redirect").alias("key"))
            .drop_nulls()
            .unique()
            .join(frame.select("key"), on="key", how="anti")
        )
        if unseen.is_empty() or frame.height + unseen.height > MAX_TITLE_ROWS:
            break
        frontier = replica.titles(wiki, unseen["key"])
        frame = pl.concat([frame, frontier])
    return frame


def _canonical_pages(titles: pl.DataFrame) -> pl.DataFrame:
    """Find main-page identities through complete redirect chains.

    Returns:
        Original title keys mapped to observed final subject IDs.
    """
    current = titles.select(
        pl.col("key").alias("original"),
        "key",
        "page_id",
        "redirect",
    )
    resolved = []
    for _ in range(REDIRECT_DEPTH + 1):
        resolved.append(
            current.filter(
                pl.col("redirect").is_null()
                & pl.col("page_id").is_not_null()
                & pl.col("key").str.starts_with("0:"),
            ).select("original", "page_id"),
        )
        current = (
            current
            .filter(pl.col("redirect").is_not_null())
            .select(
                "original",
                pl.col("redirect").alias("key"),
            )
            .join(titles, on="key", how="inner", validate="m:1")
        )
        if current.is_empty():
            break
    return pl.concat(resolved)


def subjects(ids: list[int]) -> dict[str, pl.DataFrame]:
    """Join scoped Chinese subjects to their English counterparts.

    Returns:
        Site-specific subject and talk identities, including absence.

    Raises:
        ValueError: The observed Chinese scope is empty.
    """
    zh = (
        replica
        .subject_pages("zhwiki", ids)
        .with_columns(
            pl.col("page_id").alias("article_id"),
            pl.lit(value=True).alias("known"),
        )
        .select(*SCHEMAS["subjects"])
    )
    if zh.is_empty():
        message = "The Article List query requires observed Chinese subjects."
        raise ValueError(message)
    sitelinks = pl.concat([
        english_sitelinks(list(batch))
        for batch in batched(zh["article_id"], _SITELINK_BATCH, strict=False)
    ]).select(
        pl.col("page_id").alias("article_id"),
        pl.concat_str(pl.lit("0:"), "english_title").alias("original"),
    )
    targets = title_facts("enwiki", sitelinks["original"].unique())
    canonical = _canonical_pages(targets)
    en = replica.subject_pages("enwiki", canonical["page_id"].unique())
    return {
        "zh": zh,
        "en": zh
        .select("article_id")
        .join(sitelinks, on="article_id", how="left", validate="1:1")
        .join(canonical, on="original", how="left", validate="m:1")
        .join(en, on="page_id", how="left", validate="m:1")
        .with_columns(
            (
                pl.col("original").is_null() | pl.col("title").is_not_null()
            ).alias("known"),
        )
        .select(*SCHEMAS["subjects"]),
    }


def _coverage(ids: Iterable[int], kind: str, depth: int = 0) -> pl.DataFrame:
    """Record the evidence from a scoped relationship read.

    Returns:
        The pages covered at the supplied kind and depth.
    """
    return pl.DataFrame(
        {"page_id": list(ids)},
        schema={"page_id": pl.Int64},
    ).with_columns(
        pl.lit(kind).alias("kind"),
        pl.lit(depth, dtype=pl.UInt8).alias("depth"),
    )


def _category_paths(
    wiki: str,
    ids: list[int],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Walk parent categories upward from the scoped members.

    Returns:
        Each member's minimum discovered distance and coverage depth.
    """
    frontier, complete = replica.edges(wiki, "cat", ids, MAX_EDGE_ROWS)
    found = frontier.with_columns(pl.lit(0, dtype=pl.UInt8).alias("depth"))
    deepest = 0
    for depth in range(1, MAX_CATEGORY_DEPTH + 1):
        if frontier.is_empty():
            deepest = MAX_CATEGORY_DEPTH
            break
        categories = replica.titles(wiki, frontier["key"].unique()).drop_nulls(
            "page_id",
        )
        parent_ids = categories["page_id"].to_list()
        parents, covered = replica.edges(
            wiki,
            "cat",
            parent_ids,
            _ANCESTOR_ROWS,
        )
        if len(parent_ids) != len(covered):
            break
        parents = parents.join(
            categories.select("key", "page_id").rename({"key": "child"}),
            on="page_id",
            how="inner",
        ).select("child", "key")
        leaves = frontier.rename({"key": "child"})
        # Bound the join before materializing broad category paths.
        fanout = (
            leaves
            .group_by("child")
            .len(name="leaves")
            .join(parents.group_by("child").len(name="parents"), on="child")
            .select((pl.col("leaves").cast(pl.Int64) * "parents").sum())
            .item()
        )
        if fanout > MAX_EDGE_ROWS - found.height:
            break
        frontier = (
            leaves
            .join(parents, on="child")
            .select("page_id", "key")
            .unique()
            .join(
                found.select("page_id", "key"),
                on=["page_id", "key"],
                how="anti",
            )
        )
        found = found.vstack(
            frontier.with_columns(
                pl.lit(depth, dtype=pl.UInt8).alias("depth"),
            ),
        )
        deepest = depth
    return found, _coverage(complete, "cat", deepest)


def _scope_keys(scope: pl.DataFrame) -> pl.DataFrame:
    """Find exact targets for incoming links.

    Returns:
        The scope's unique subject and discussion IDs and titles.
    """
    frames = [
        scope
        .select(
            pl.col(column).alias("page_id"),
            pl.concat_str(pl.lit(prefix), "title").alias("target"),
        )
        .drop_nulls()
        .unique()
        for prefix, column in (("0:", "page_id"), ("1:", "talk_id"))
    ]
    return pl.concat(frames)


def _alias_targets(
    wiki: str,
    direct: pl.DataFrame,
) -> tuple[pl.DataFrame, set[int]]:
    """Follow reverse redirects with bounded, cycle-safe traversal.

    Returns:
        Alias targets and subject IDs with incomplete alias coverage.
    """
    seen = direct
    frontier = direct
    incomplete: set[int] = set()
    for _ in range(REDIRECT_DEPTH):
        keys = frontier["target"].unique()
        edges, complete = replica.incoming_redirects(
            wiki,
            keys,
            _REDIRECT_ROWS,
        )
        if len(keys) != len(complete):
            incomplete.update(
                frontier.filter(~pl.col("target").is_in(list(complete)))[
                    "page_id"
                ],
            )
        frontier = (
            frontier
            .join(edges, on="target")
            .select("page_id", pl.col("key").alias("target"))
            .unique()
            .join(seen, on=["page_id", "target"], how="anti")
        )
        if frontier.is_empty():
            break
        seen = seen.vstack(frontier)
    else:
        incomplete.update(frontier["page_id"])
    return seen.join(direct, on=["page_id", "target"], how="anti"), incomplete


def _incoming(
    wiki: str,
    scope: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Read literal and redirect-target backlinks.

    Returns:
        Incoming relationships and their independent coverage.
    """
    targets = _scope_keys(scope)
    direct, complete = replica.backlinks(
        wiki,
        targets["target"],
        MAX_EDGE_ROWS,
    )
    direct_ids = set(
        targets.filter(pl.col("target").is_in(list(complete)))["page_id"],
    )
    aliases, incomplete = _alias_targets(wiki, targets)
    redirected, alias_complete = replica.backlinks(
        wiki,
        aliases["target"],
        MAX_EDGE_ROWS - direct.height,
    )
    incomplete.update(
        aliases.filter(~pl.col("target").is_in(list(alias_complete)))[
            "page_id"
        ],
    )
    edges = pl.concat([
        relation.join(names, on="target").select(
            "page_id",
            "key",
            pl.lit(via).alias("via_redirect"),
        )
        for relation, names, via in (
            (direct, targets, False),
            (redirected, aliases, True),
        )
    ]).unique()
    followed = direct_ids - incomplete
    return edges, pl.concat([
        _coverage(direct_ids - followed, "backlink"),
        _coverage(followed, "backlink", 1),
    ])


def _variants(
    wiki: str,
    facts: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Verify generated Chinese aliases using exact replica titles.

    Returns:
        The extended title facts and aliases with absent exact titles.
    """
    if wiki != "zhwiki":
        return facts, pl.DataFrame(schema=SCHEMAS["variants"])
    known = facts.filter(pl.col("page_id").is_not_null())["key"]
    pairs = [
        (alias, title)
        for title in known.head(_VARIANT_TITLES)
        for alias in script_alternatives(title)
    ]
    variants = pl.DataFrame(pairs, schema=SCHEMAS["variants"], orient="row")
    new = (
        variants
        .select("key")
        .unique()
        .join(
            facts.select("key"),
            on="key",
            how="anti",
        )
    )
    extra = replica.titles(wiki, new["key"])
    facts = facts.vstack(extra)
    variants = variants.join(
        facts.filter(pl.col("page_id").is_null()).select("key"),
        on="key",
        how="semi",
    ).unique()
    return facts, variants


def partitions(
    scopes: dict[str, pl.DataFrame],
) -> Iterator[tuple[str, str, pl.DataFrame]]:
    """Prepare typed query tables by site.

    Yields:
        Complete named partitions for an atomic cache publish.
    """
    for site, scope in scopes.items():
        wiki = f"{site}wiki"
        subjects_only = scope["page_id"].drop_nulls().unique().sort().to_list()
        ids = sorted(set(subjects_only).union(scope["talk_id"].drop_nulls()))
        yield site, "subjects", scope
        yield site, "projects", replica.project_names(wiki)
        assessed, complete = replica.assessments(
            wiki,
            subjects_only,
            MAX_EDGE_ROWS,
        )
        yield site, "assessment", assessed
        coverage = [_coverage(complete, "assessment")]
        keys = dict.fromkeys(
            [f"14:{name}" for name in ARTICLE_GRADE_CATEGORIES]
            if site == "zh"
            else [_EN_CATEGORY],
        )
        keys.update(dict.fromkeys(_scope_keys(scope)["target"]))
        categories, observed = _category_paths(wiki, ids)
        yield site, "cat", categories
        keys.update(dict.fromkeys(categories["key"].unique()))
        coverage.append(observed)
        for kind in ("tl", "link"):
            edges, complete = replica.edges(wiki, kind, ids, MAX_EDGE_ROWS)
            yield site, kind, edges
            keys.update(dict.fromkeys(edges["key"].unique()))
            coverage.append(_coverage(complete, kind))
        incoming, observed = _incoming(wiki, scope)
        yield site, "backlink", incoming
        keys.update(dict.fromkeys(incoming["key"].unique()))
        coverage.append(observed)
        yield site, "coverage", pl.concat(coverage)
        facts = title_facts(wiki, list(keys)[:MAX_TITLE_ROWS])
        facts, variants = _variants(wiki, facts)
        yield site, "titles", facts
        yield site, "variants", variants
