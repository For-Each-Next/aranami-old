"""Exercise cross-wiki relationships and title correction."""

# Fixture IDs and threshold values are literal.
# ruff: file-ignore[magic-value-comparison]

from __future__ import annotations

import datetime as dt
import json
from base64 import urlsafe_b64encode
from hashlib import sha256
from http import HTTPStatus
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import polars as pl
from starlette.testclient import TestClient

from data.articles import quality_pages, query_index
from data.articles.article_query import ArticleQuery, QueryOptions
from data.caching.article_query_checks import TitleChecks
from shared.article_query import QuerySyntaxError, parse, title_key
from tasks.articles import article_query as collection
from webservice.server import create_app

_ZH_CATEGORY = "14:小作品级电子游戏条目"
_ZH_TRADITIONAL = "14:小作品級電子遊戲條目"
_EN_CATEGORY = "14:B-Class_video_game_articles"
_CANDIDATES = [1, 2, 3, 4]
_NOW = dt.datetime(2026, 11, 21, 14, 40, tzinfo=dt.UTC)
_DEFAULT_OPTIONS = QueryOptions()


def _partitions() -> list[tuple[str, str, pl.DataFrame]]:
    """Build a small saved corpus with partial relationship coverage.

    Returns:
        Typed partitions for both sites and every relationship.
    """
    zh = {
        "subjects": [
            (1, 1, 11, "甲", True),
            (2, 2, 22, "乙", True),
            (3, 3, None, "丙", True),
            (4, 4, None, "丁", True),
        ],
        "assessment": [
            (1, "电子游戏", "小作品", "低"),
            (2, "电子游戏", "小列表", "高"),
        ],
        "projects": [("电子游戏",)],
        "cat": [(11, _ZH_CATEGORY, 0), (22, "14:Uncreated", 0)],
        "link": [(1, "0:Alias"), (2, "0:Redlink")],
        "tl": [(2, "10:Missing_template")],
        "backlink": [(1, "0:Source", True)],
        "coverage": [
            *[(page, "cat", 5) for page in (1, 2, 3, 4, 11, 22)],
            *[(page, "link", 0) for page in _CANDIDATES],
            *[(page, "tl", 0) for page in _CANDIDATES],
            *[(page, "backlink", 1) for page in _CANDIDATES],
            *[(page, "assessment", 0) for page in _CANDIDATES],
        ],
        "titles": [
            (_ZH_CATEGORY, 80, None),
            (_ZH_TRADITIONAL, None, None),
            ("14:Uncreated", None, None),
            ("0:Alias", 90, "0:Target"),
            ("0:Target", 91, None),
            ("0:Redlink", None, None),
            ("0:Source", 92, None),
            ("10:Missing_template", None, None),
        ],
        "variants": [(_ZH_TRADITIONAL, _ZH_CATEGORY)],
    }
    en = {
        "subjects": [
            (1, 1001, 1011, "First_game", True),
            (2, 1002, None, "Second_game", True),
            (3, None, None, None, True),
            (4, None, None, None, False),
        ],
        "assessment": [
            (1001, "Video games", "B", "High"),
            (1002, "Video games", "Start", "Low"),
            (1002, "Software", "B", "High"),
        ],
        "projects": [("Video games",), ("Software",)],
        "cat": [(1011, _EN_CATEGORY, 0), (1011, "14:Video_games", 2)],
        "coverage": [
            (1011, "cat", 5),
            (1001, "assessment", 0),
            (1002, "assessment", 0),
        ],
        "titles": [(_EN_CATEGORY, 180, None), ("14:Video_games", 181, None)],
    }
    return [
        (
            site,
            name,
            pl.DataFrame(tables.get(name, []), schema=schema, orient="row"),
        )
        for site, tables in (("zh", zh), ("en", en))
        for name, schema in query_index.SCHEMAS.items()
    ]


class TestArticleQuery(TestCase):
    """Evaluate the same saved generation in preview and execution."""

    def setUp(self) -> None:
        """Publish a complete offline generation."""
        self.runtime = Path(self.enterContext(TemporaryDirectory())).resolve()
        query_index.publish(self.runtime, _NOW, _partitions())
        self.index = query_index.load(self.runtime)

    def query(
        self,
        source: str,
        options: QueryOptions = _DEFAULT_OPTIONS,
    ) -> ArticleQuery:
        """Build an expression against the retained fixture.

        Returns:
            The scoped expression and saved title observations.
        """
        return ArticleQuery(parse(source), self.index, options)

    def test_precedence_and_keyword_errors(self) -> None:
        """Check operator precedence and invalid options."""
        tree = parse('link("A") | ~tl("B") & cat({"C", "D"}, depth=2)')
        assert tree["op"] == "or"
        right = tree["children"][1]
        assert right["op"] == "and"
        assert right["children"][0]["op"] == "not"
        for source in (
            'cat("x", depth=6)',
            'class("x", on="talk")',
            'cat("x", site="de")',
            'cat("x", on="talk", on="main")',
            'link("x") &',
            "cat({})",
            'exec("x")',
        ):
            with (
                self.subTest(source=source),
                self.assertRaises(QuerySyntaxError),  # ruff: ignore[pytest-unittest-raises-assertion]
            ):
                parse(source)

    def test_talk_is_explicit_and_variant_is_reversible(self) -> None:
        """Apply the Traditional alias locally only when selected."""
        literal = '"小作品級電子遊戲條目"'
        talk = self.query(f'cat({literal}, on="talk")')
        assert talk.preview()[0]["status"] == "variant"
        assert talk.preview()[0]["resolved"] == "Category:小作品级电子游戏条目"
        assert talk.select(_CANDIDATES) == ({1}, 0)
        assert self.query(f"cat({literal})").select(_CANDIDATES) == (set(), 0)
        exact = self.query(
            f'cat({literal}, on="talk")',
            QueryOptions(variants=False),
        )
        assert exact.preview()[0]["status"] == "missing"
        assert exact.select(_CANDIDATES) == (set(), 0)
        assert (
            title_key("zh", "cat", "分類:小作品級電子遊戲條目")
            == _ZH_TRADITIONAL
        )

    def test_article_assessments_join_counterparts_by_site_and_project(
        self,
    ) -> None:
        """Read English grades and importance from one project row."""
        query = self.query(
            'class("B", project="Video games", site="en") '
            '& imp("High", site="en") & class({"小作品", "小列表"})',
        )
        assert query.select(_CANDIDATES) == ({1}, 0)
        assert query.counterparts([1]) == {1: "First_game"}
        assert self.query(
            'wp("Software", class="B", importance="High", site="en")',
        ).select(_CANDIDATES) == ({2}, 1)

    def test_true_missing_and_unknown_are_distinct(self) -> None:
        """Keep unverified counterparts out of the complement."""
        assert self.query('~has_wiki("en")').select(_CANDIDATES) == ({3}, 1)
        assert self.query(
            '~has_wiki("en") | class("B", site="en")',
        ).select(_CANDIDATES) == ({1, 3}, 1)

    def test_missing_title_warnings_preserve_recorded_relationships(
        self,
    ) -> None:
        """Match links and categories with missing target pages."""
        query = self.query(
            'link("Redlink") & tl("Missing template") '
            '& cat("Uncreated", on="talk")',
        )
        assert [entry["status"] for entry in query.preview()] == [
            "missing",
        ] * 3
        assert query.select(_CANDIDATES) == ({2}, 0)

    def test_uncached_title_uses_background_facts(self) -> None:
        """Queue unknown titles and reuse confirmed facts."""
        checks = Mock(spec=TitleChecks)
        checks.read.return_value = {}
        tree = parse('link("Unchecked title")')
        key = "zh", "0:Unchecked_title"
        pending = ArticleQuery(tree, self.index, _DEFAULT_OPTIONS, checks)
        assert pending.preview()[0]["status"] == "unverified"
        checks.request.assert_called_once_with({key})
        assert pending.select(_CANDIDATES) == (set(), len(_CANDIDATES))
        checks.read.return_value = {
            key: {"titles": {key[1]: (None, None)}, "variants": []},
        }
        settled = ArticleQuery(tree, self.index, _DEFAULT_OPTIONS, checks)
        assert settled.preview()[0]["status"] == "missing"
        assert settled.select(_CANDIDATES) == (set(), 0)

    def test_directions_depth_and_redirects(self) -> None:
        """Check direction, category ancestry and redirect policy."""
        query = self.query('link("Target") & backlink("Source")')
        assert query.select(_CANDIDATES) == ({1}, 0)
        literal = self.query('link("Target")', QueryOptions(redirects=False))
        assert literal.select(_CANDIDATES) == (set(), 0)
        ancestor = 'cat("Video games", on="talk", site="en", depth='
        assert self.query(ancestor + "2)").select(_CANDIDATES) == ({1}, 1)
        assert self.query(ancestor + "1)").select(_CANDIDATES) == (set(), 1)

    def test_snapshot_replacement_retains_previous_and_failed_write(
        self,
    ) -> None:
        """Keep the selected generation when a staged write fails."""
        first = self.index.generation
        with self.assertRaises(ValueError):  # ruff: ignore[pytest-unittest-raises-assertion]
            query_index.publish(self.runtime, _NOW + dt.timedelta(hours=1), [])
        assert query_index.load(self.runtime).generation == first
        query_index.publish(
            self.runtime,
            _NOW + dt.timedelta(hours=1),
            _partitions(),
        )
        assert query_index.load(self.runtime, first).generation == first
        assert query_index.load(self.runtime).generation != first

    def test_public_preview_and_directory_use_same_snapshot(self) -> None:
        """Run a saved query against the confirmed matrix cohort."""
        saved = json.dumps({
            "articles": [
                {
                    "page_id": article,
                    "title": title,
                    "grade": "Bplus",
                    "importance": "High",
                    "listed_date": None,
                }
                for article, title in ((1, "甲"), (2, "乙"))
            ],
            "authors": {},
            "grades": ["Bplus", "Stub"],
            "importance": ["High"],
            "last_year": 2026,
        })
        name = f"directory-{sha256(saved.encode()).hexdigest()}.json"
        quality_pages.save(
            quality_pages.path_for(self.runtime, "en", basis="current"),
            "<p>Fixture</p>",
            ("source",),
            resources={name: saved},
        )
        client = TestClient(create_app(self.runtime))
        expression = 'class("B", project="Video games", site="en")'
        response = client.get(
            "/article-list/query/",
            params={"expression": expression, "preview": "1"},
        )
        assert response.status_code == HTTPStatus.OK
        preview = response.json()
        assert preview["checks"][0]["status"] == "exists"
        assert preview["generation"] == self.index.generation
        query = {
            "view": "articles",
            "expression": expression,
            "query_generation": preview["generation"],
            "cells": ["Bplus:High"],
            "first": 2009,
            "last": 2026,
            "unknown": True,
        }
        url = "/article-list/resources/en/0/current/" + name
        encoded = urlsafe_b64encode(json.dumps(query).encode()).decode()
        response = client.get(url, params={"q": encoded})
        assert response.status_code == HTTPStatus.OK
        result = response.json()
        assert result["cohort"] == 2
        assert result["total"] == 1
        assert result["rows"][0][0] == 1
        assert result["counterparts"] == {"1": "First_game"}
        response = client.get(
            "/article-list/query/",
            params={"expression": "cat("},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT


class TestCategoryCollection(TestCase):
    """Keep minimum distance when a category graph loops."""

    @staticmethod
    def test_cycle_closure() -> None:
        """Return the direct category and its ancestor exactly once."""
        links = {1: "14:Child", 20: "14:Parent", 30: "14:Child"}
        page_ids = {"14:Child": 20, "14:Parent": 30}

        def category_edges(
            _wiki: str,
            _kind: str,
            ids: list[int],
            _limit: int,
        ) -> tuple[pl.DataFrame, set[int]]:
            return (
                pl.DataFrame(
                    [(page, links[page]) for page in ids],
                    schema={"page_id": pl.Int64, "key": pl.String},
                    orient="row",
                ),
                set(ids),
            )

        def title_facts(_wiki: str, keys: pl.Series) -> pl.DataFrame:
            return pl.DataFrame(
                [(key, page_ids[key]) for key in keys],
                schema={"key": pl.String, "page_id": pl.Int64},
                orient="row",
            )

        with (
            patch.object(
                collection.replica,
                "edges",
                side_effect=category_edges,
            ),
            patch.object(
                collection.replica,
                "titles",
                side_effect=title_facts,
            ),
        ):
            paths, coverage = collection._category_paths("zhwiki", [1])  # ruff: ignore[private-member-access]
        assert paths.sort("depth").rows() == [
            (1, "14:Child", 0),
            (1, "14:Parent", 1),
        ]
        assert coverage["depth"].item() == 5
