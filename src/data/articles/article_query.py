"""Evaluate Article List predicates against saved replica data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from data.articles.query_index import MAX_TITLE_ROWS
from shared.article_query import (
    PAGE_PREDICATES,
    PROJECTS,
    title_key,
    title_label,
    values,
)
from shared.assessment_profiles import assessment_profile

if TYPE_CHECKING:
    from collections.abc import Iterator

    from data.articles.query_index import QueryIndex
    from data.caching.article_query_checks import CheckKey, TitleChecks
    from shared.article_query import Expression, Predicate

_REDIRECT_DEPTH = 8
_REQUEST_CACHE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class QueryOptions:
    """Select independent title resolution policies."""

    redirects: bool = True
    variants: bool = True


@dataclass(frozen=True, slots=True)
class _Title:
    """Describe a literal lookup and the effective relationship key."""

    key: str
    status: str
    suggestions: tuple[str, ...] = ()
    changed_by: str | None = None


@dataclass(frozen=True, slots=True)
class _Truth:
    """Keep confirmed true and false rows."""

    yes: set[int]
    no: set[int]


def _terms(tree: Expression | None) -> Iterator[Predicate]:
    """Yield predicate leaves in the order displayed in the editor."""
    if tree is None:
        return
    if tree["op"] == "term":
        yield tree
        return
    for child in tree["children"]:
        yield from _terms(child)


def _site(term: Predicate) -> str:
    """Select the wiki for a term.

    Returns:
        The validated wiki code.
    """
    if term["name"] == "has_wiki":
        return str(term["value"])
    return str(term["options"].get("site", "zh"))


def _projects(term: Predicate) -> list[str]:
    """Select the projects whose assessments determine a term.

    Returns:
        Literal project names or the configured default for that wiki.
    """
    if term["name"] == "wp":
        return [project.strip() for project in values(term["value"])]
    return [str(term["options"].get("project", PROJECTS[_site(term)])).strip()]


class ArticleQuery:
    """Use the same saved titles for preview and execution."""

    def __init__(
        self,
        tree: Expression | None,
        index: QueryIndex | None,
        options: QueryOptions,
        checks: TitleChecks | None = None,
    ) -> None:
        """Resolve the titles and settings used by the query."""
        self.tree = tree
        self.index = index
        self.options = options
        self._frames: dict[tuple[str, str], pl.DataFrame] = {}
        self._cached_bytes = 0
        self._sites = {_site(term) for term in _terms(tree)}
        self._titles = self._load_titles(checks)

    def _read(self, site: str, name: str) -> pl.DataFrame:
        """Reuse the selected partition during this evaluation.

        Returns:
            The already opened or newly validated table.
        """
        key = site, name
        if key in self._frames:
            return self._frames[key]
        frame = self.index.read(site, name)
        size = frame.estimated_size()
        if self._cached_bytes + size <= _REQUEST_CACHE_BYTES:
            self._frames[key] = frame
            self._cached_bytes += size
        return frame

    def _load_titles(
        self,
        checks: TitleChecks | None,
    ) -> dict[CheckKey, _Title]:
        """Combine snapshot facts and completed uncached checks.

        Returns:
            Resolution and status for each site and title in the query.
        """
        pairs = {
            (_site(term), title_key(_site(term), term["name"], value))
            for term in _terms(self.tree)
            if term["name"] in PAGE_PREDICATES
            for value in values(term["value"])
        }
        facts: dict[CheckKey, tuple[int | None, str | None]] = {}
        suggestions: dict[CheckKey, tuple[str, ...]] = {}
        for site in sorted({site for site, _ in pairs}):
            keys = {key for code, key in pairs if code == site}
            if self.index is None:
                continue
            variants = self._read(site, "variants").filter(
                pl.col("key").is_in(list(keys)),
            )
            for key, targets in (
                variants.group_by("key").agg("target").iter_rows()
            ):
                suggestions[site, key] = tuple(sorted(targets))
            keys.update(variants["target"])
            table = self._read(site, "titles")
            for _ in range(_REDIRECT_DEPTH + 1):
                observed = table.filter(pl.col("key").is_in(list(keys)))
                facts.update({
                    (site, key): (page_id, redirect)
                    for key, page_id, redirect in observed.iter_rows()
                })
                keys = {
                    target
                    for target in observed["redirect"].drop_nulls()
                    if (site, target) not in facts
                }
                if not keys:
                    break
        pending = {
            (site, key)
            for site, key in pairs
            if (site, key) not in facts
            or (
                site == "zh"
                and self.options.variants
                and facts[site, key][0] is None
                and (site, key) not in suggestions
            )
        }
        if checks is not None:
            answers = checks.read(pending)
            for (site, key), result in answers.items():
                for name, fact in result["titles"].items():
                    facts.setdefault((site, name), tuple(fact))
                suggestions.setdefault((site, key), tuple(result["variants"]))
            checks.request(pending - answers.keys())
        return {
            (site, key): self._resolve(
                site,
                key,
                facts,
                suggestions.get((site, key), ()),
            )
            for site, key in pairs
        }

    def _resolve(
        self,
        site: str,
        key: str,
        facts: dict[CheckKey, tuple[int | None, str | None]],
        variants: tuple[str, ...],
    ) -> _Title:
        """Apply the selected lookup policy to a literal title.

        Returns:
            An exact or resolved key, its status, and any suggestions.
        """
        current = key
        changed_by = None
        if (site, key) not in facts:
            return _Title(key, "unverified")
        if facts[site, key][0] is None and self.options.variants:
            if len(variants) > 1:
                return _Title(key, "ambiguous", variants)
            if variants:
                current = variants[0]
                changed_by = "variant"
        seen = set()
        for _ in range(_REDIRECT_DEPTH + 1):
            if (site, current) not in facts or current in seen:
                return _Title(key, "unverified", variants)
            page_id, redirect = facts[site, current]
            if not self.options.redirects or redirect is None:
                status = changed_by or "exists"
                return _Title(
                    current,
                    status if page_id else "missing",
                    variants,
                    changed_by,
                )
            seen.add(current)
            current = redirect
            changed_by = changed_by or "redirect"
        return _Title(key, "unverified", variants)

    def preview(self) -> list[dict]:
        """Describe references in their original query order.

        Returns:
            Advisory statuses and source spans for the two editors.
        """
        result = []
        for term in _terms(self.tree):
            site, name = _site(term), term["name"]
            if name in PAGE_PREDICATES:
                for entered in values(term["value"]):
                    key = title_key(site, name, entered)
                    title = self._titles[site, key]
                    result.append({
                        "site": site,
                        "kind": name,
                        "entered": entered,
                        "resolved": title_label(title.key)
                        if title.key != key
                        else None,
                        "status": title.status,
                        "suggestions": [
                            title_label(candidate)
                            for candidate in title.suggestions
                        ],
                        "start": term["start"],
                        "end": term["end"],
                    })
            elif name in {"class", "imp", "wp"}:
                projects = (
                    set(self._read(site, "projects")["project"])
                    if self.index is not None
                    else None
                )
                for project in _projects(term):
                    status = "unverified"
                    if projects is not None:
                        status = "exists" if project in projects else "missing"
                    result.append({
                        "site": site,
                        "kind": "wp",
                        "entered": project,
                        "status": status,
                        "start": term["start"],
                        "end": term["end"],
                    })
        return result

    def _aliases(self, site: str, keys: set[str]) -> set[str]:
        """Expand the targets under the active alias settings.

        Returns:
            Exact keys and supported aliases for relationship matching.
        """
        keys = set(keys)
        if self.options.redirects:
            titles = self._read(site, "titles").drop_nulls("redirect")
            frontier = keys
            for _ in range(_REDIRECT_DEPTH):
                frontier = (
                    set(
                        titles.filter(
                            pl.col("redirect").is_in(list(frontier)),
                        )["key"],
                    )
                    - keys
                )
                if not frontier:
                    break
                keys.update(frontier)
        if self.options.variants and site == "zh":
            variants = self._read(site, "variants")
            observed = (
                variants
                .group_by("key")
                .agg(
                    pl.len().alias("count"),
                    pl.first("target"),
                )
                .filter(
                    (pl.col("count") == 1)
                    & pl.col("target").is_in(list(keys)),
                )
            )
            keys.update(observed["key"])
        return keys

    def _page_hits(
        self,
        site: str,
        term: Predicate,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Find matches in the saved page relationships.

        Returns:
            Matching page IDs and IDs with complete observations.
        """
        name = term["name"]
        resolutions = [
            self._titles[site, title_key(site, name, value)]
            for value in values(term["value"])
        ]
        edges = self._read(site, name)
        depth = int(term["options"].get("depth", 0))
        keys = {title.key for title in resolutions}
        if name == "backlink":
            if not self.options.redirects:
                edges = edges.filter(~pl.col("via_redirect"))
            depth = int(self.options.redirects)
        else:
            keys = self._aliases(site, keys)
        if name == "cat":
            edges = edges.filter(pl.col("depth") <= depth)
        matched = (
            edges
            .filter(pl.col("key").is_in(list(keys)))
            .select("page_id")
            .unique()
        )
        covered = self._covered(site, name, depth)
        if self.options.redirects and name != "backlink":
            titles = self._read(site, "titles")
            if titles.height >= MAX_TITLE_ROWS:
                incomplete = edges.join(
                    titles.select("key"),
                    on="key",
                    how="anti",
                ).select("page_id")
                covered = covered.join(incomplete, on="page_id", how="anti")
        if any(title.status == "unverified" for title in resolutions) and (
            self.options.redirects or (self.options.variants and site == "zh")
        ):
            covered = covered.clear()
        return matched, covered

    def _covered(self, site: str, kind: str, depth: int = 0) -> pl.DataFrame:
        """Locate pages with enough evidence to evaluate absence.

        Returns:
            IDs fully observed at the requested depth.
        """
        return (
            self
            ._read(site, "coverage")
            .filter(
                (pl.col("kind") == kind) & (pl.col("depth") >= depth),
            )
            .select("page_id")
            .unique()
        )

    def _assessment_hits(self, site: str, term: Predicate) -> pl.DataFrame:
        """Match assessment fields within the named project.

        Returns:
            Subject IDs whose project membership satisfies the term.
        """
        name, options = term["name"], term["options"]
        fields = {
            "class": term["value"]
            if name == "class"
            else options.get("class"),
            "importance": term["value"]
            if name == "imp"
            else options.get("importance"),
        }
        assessments = self._read(site, "assessment")
        matches = []
        for project in _projects(term):
            profile = assessment_profile(f"{site}wiki", project)
            keep = pl.col("project") == project
            for dimension, raw in fields.items():
                if raw is not None:
                    codes = [
                        profile.code(value, dimension) for value in values(raw)
                    ]
                    column = "grade" if dimension == "class" else "importance"
                    keep &= profile.expression(column, dimension).is_in(codes)
            matches.append(assessments.filter(keep).select("page_id"))
        return pl.concat(matches).unique()

    def _leaf(self, term: Predicate, ids: list[int]) -> _Truth:
        """Map one site's matches back to Chinese subjects.

        Returns:
            Confirmed positive and negative subject IDs.
        """
        site, name = _site(term), term["name"]
        scope = self._read(site, "subjects").filter(
            pl.col("article_id").is_in(ids) & pl.col("known"),
        )
        if name == "has_wiki":
            known = set(scope["article_id"])
            present = set(
                scope.filter(pl.col("page_id").is_not_null())["article_id"],
            )
            return _Truth(present, known - present)
        if name in PAGE_PREDICATES:
            if term["options"].get("on") == "talk":
                scope = scope.drop("page_id").rename({"talk_id": "page_id"})
            matches, covered = self._page_hits(site, term)
        else:
            matches, covered = (
                self._assessment_hits(site, term),
                self._covered(
                    site,
                    "assessment",
                ),
            )
        absent = set(scope.filter(pl.col("page_id").is_null())["article_id"])
        positive = set(
            scope.join(matches, on="page_id", how="semi")["article_id"],
        )
        known = set(
            scope.join(covered, on="page_id", how="semi")["article_id"],
        )
        return _Truth(positive, (known | absent) - positive)

    def _evaluate(self, node: Expression, ids: list[int]) -> _Truth:
        """Apply three-valued Boolean operations.

        Returns:
            The confirmed truth sets for this node.
        """
        operator = node["op"]
        if operator == "term":
            return self._leaf(node, ids)
        first, *others = node["children"]
        result = self._evaluate(first, ids)
        if operator == "not":
            return _Truth(result.no, result.yes)
        for child in others:
            other = self._evaluate(child, ids)
            if operator == "and":
                result = _Truth(result.yes & other.yes, result.no | other.no)
            else:
                result = _Truth(result.yes | other.yes, result.no & other.no)
        return result

    def select(self, ids: list[int]) -> tuple[set[int], int]:
        """Apply the expression to the selected directory cohort.

        Returns:
            Matching IDs and the number of rows with unknown truth.
        """
        if self.tree is None:
            return set(ids), 0
        if self.index is None:
            return set(), len(ids)
        result = self._evaluate(self.tree, ids)
        return result.yes, len(ids) - len(result.yes) - len(result.no)

    def counterparts(self, ids: list[int]) -> dict[int, str]:
        """Select counterparts for visible cross-wiki result rows.

        Returns:
            Chinese subject IDs mapped to their saved English titles.
        """
        if self.index is None or "en" not in self._sites or not ids:
            return {}
        return dict(
            self
            ._read("en", "subjects")
            .filter(
                pl.col("article_id").is_in(ids)
                & pl.col("title").is_not_null(),
            )
            .select("article_id", "title")
            .iter_rows(),
        )
