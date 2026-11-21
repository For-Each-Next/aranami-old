"""Verify annual intervals and historical statistics."""

# Exact dates and counts express regression fixtures.
# ruff: file-ignore[magic-value-comparison, ambiguous-unicode-character-string]

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import mwparserfromhell
import polars as pl
from PIL import Image

from data.newsletter.figures import annual_figures
from data.newsletter.grades import QUALITY_GRADES
from shared.newsletter import Issue
from tasks.zhwiki.legacy.newsletter_figures import prepare_dyk_series
from tasks.zhwiki.legacy.newsletter_popularity import parse_popularity
from tasks.zhwiki.newsletter.statistics import (
    collect_popularity,
    quality_statistics,
)
from updater.services.newsletter_editorial import render_annual_feature
from webservice import newsletter_png
from webservice.newsletter_charts import (
    CHART_DIRECTORY,
    available_charts,
    prepare_newsletter_charts,
)


def _popular(start: str, end: str, duration: str = "yearly") -> str:
    """Build a verified HOT/v2-shaped source with an explicit interval.

    Returns:
        Wikitext containing one project ranking and its measured totals.
    """
    data = {
        "metadata": {
            "project": "电子游戏",
            "duration": duration,
            "start": list(dt.date.fromisoformat(start).timetuple()[:3]),
            "end": list(dt.date.fromisoformat(end).timetuple()[:3]),
            "total_pages": 13000,
            "total_views": 36600000,
        },
        "items": [{"title": "Game", "views": 31000}],
    }
    heading = "月瀏覽量" if duration == "monthly" else "年瀏覽量"
    return (
        f"=== {heading} ===\n{{{{#invoke:PJ:VG/HOT/v2|main|data="
        f"{json.dumps(data)} <!-- #endinvoke -->}}}}"
    )


def _preceding_introduction(
    code: mwparserfromhell.wikicode.Wikicode,
    node: mwparserfromhell.nodes.Node,
) -> str:
    """Read the paragraph immediately preceding a displayed block.

    Returns:
        Introduction prose without the following list or figure.
    """
    position = next(
        index
        for index, candidate in enumerate(code.nodes)
        if candidate is node
    )
    prefix = "".join(map(str, code.nodes[:position]))
    return prefix.rstrip().rsplit("\n\n", 1)[-1]


def _with_dyk_series(review: dict) -> dict:
    """Prepare explicit chart facts before invoking the pure renderer.

    Returns:
        Fixture observations with an audited cumulative series.
    """
    return {**review, "dyk_series": prepare_dyk_series(review, 2026)}


def _partial_annual_review() -> dict:
    """Prepare all annual figures and lists with distinct cutoff dates.

    Returns:
        Partial observations whose DYK chart ends before the report.
    """
    return _with_dyk_series({
        "complete": False,
        "observation_end": "2026-11-01",
        "quality_statistics": [
            {
                "year": year,
                "counts": {**dict.fromkeys(QUALITY_GRADES, 0), "fa": 10},
                "provisional": year == 2026,
            }
            for year in (2025, 2026)
        ],
        "quality_year_ends": [
            {
                "year": year,
                "grades": {
                    **dict.fromkeys(("FA", "FL", "A", "AL", "GA", "Bplus"), 0),
                    "FA": 1,
                },
            }
            for year in (2025, 2026)
        ],
        "quality_changes": [
            {
                "title": "Quality",
                "date": "2026-03-01",
                "grade": "FA",
                "action": "added",
                "nominator": "Editor",
                "authors": ["Editor"],
            },
        ],
        "dyk": [{"title": "DYK", "date": "2026-03-01"}],
        "dyk_new_quarters": [{"date": "2026-09-30", "count": 1}],
        "monthly_popularity": [
            {"month": 1, "days": 31, "title": "Monthly", "views": 31000},
        ],
        "annual_popularity": {
            "start": "2026-01-01",
            "end": "2026-10-31",
            "items": [{"title": "Popular", "views": 31000}],
            "article_count": 1,
            "total_views": 31000,
            "provisional": True,
        },
        "revision_ranking": [{"title": "Revised", "revisions": 123}],
        "awards": [{"user": "Editor", "gained": 12, "total": 12}],
        "newcomers": ["Editor"],
    })


class NewsletterStatisticsTests(TestCase):
    """Keep annual charts and calendar boundaries accurate."""

    @staticmethod
    def test_pie_percentages_apply_exact_five_percent_boundary() -> None:
        """Keep raw geometry and omit rounded-up subthreshold shares."""
        review = {
            "quality_statistics": [
                {
                    "year": year,
                    "counts": {
                        **dict.fromkeys(QUALITY_GRADES, 0),
                        "fa": 499,
                        "fl": 500,
                        "a": 5150,
                        "ga": 3851,
                    },
                    "provisional": year == 2026,
                }
                for year in (2025, 2026)
            ],
        }
        text = render_annual_feature(Issue(2027, 1), review)
        chart = annual_figures(review, 2026)[3]
        counts = tuple(series.counts[0] for series in chart.series)
        assert counts == (499, 500, 5150, 3851)
        assert newsletter_png._percentages(counts) == (  # ruff: ignore[private-member-access]
            "",
            "5.0%",
            "51.5%",
            "38.5%",
        )
        issue = Issue(2027, 1)
        with TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            payload = {
                "issues": {
                    "2026-01": {"year_review": review},
                    issue.value: {"year_review": review},
                },
            }
            prepare_newsletter_charts(runtime, payload)
            files = sorted((runtime / CHART_DIRECTORY).glob("*.png"))
            assert len(files) == 3
            for path in files:
                with Image.open(path) as image:
                    assert image.format == "PNG"
                    assert image.size == (1440, 860)
                    image.verify()
            previews = available_charts(runtime, issue, review)
            assert len(previews) == 3
            assert all(item["filename"] in text for item in previews)
            assert "WPVG Newsletter 202601 Feature Graph 3" in text
            stamps = [path.stat().st_mtime_ns for path in files]
            prepare_newsletter_charts(runtime, payload)
            assert stamps == [path.stat().st_mtime_ns for path in files]

    @staticmethod
    def test_zero_pie_counts_do_not_create_percentages() -> None:
        """Skip empty pies without inventing percentages."""
        text = render_annual_feature(
            Issue(2027, 1),
            {
                "quality_statistics": [
                    {
                        "year": year,
                        "counts": dict.fromkeys(QUALITY_GRADES, 0),
                        "provisional": year == 2026,
                    }
                    for year in (2025, 2026)
                ],
            },
        )
        assert "Feature Graph 3" not in text

    @staticmethod
    def test_current_and_legacy_popularity_contracts() -> None:
        """Read both verified popularity report formats."""
        current = parse_popularity(
            _popular("2026-01-01", "2026-12-31"),
            "yearly",
        )
        assert current["items"] == [{"title": "Game", "views": 31000}]
        assert current["total_views"] == 36600000
        legacy = (
            "=== 月瀏覽量 ===\n"
            "{{PJ:VG/HOT/header|start=2026-01-01|end=2026-01-31|"
            "page_count=12534|total_views=5751704|tag=vg|limit=100}}\n"
            "# {{PJ:VG/HOT/item|Music|丙|低|views=40,710|rank=1}}\n"
            "{{PJ:VG/HOT/footer}}"
        )
        parsed = parse_popularity(legacy, "monthly")
        assert parsed["start"] == "2026-01-01"
        assert parsed["items"] == [{"title": "Music", "views": 40710}]
        assert (
            parse_popularity(legacy.replace("tag=vg", "tag=se"), "monthly")
            is None
        )

    @staticmethod
    def test_months_require_exact_calendar_intervals() -> None:
        """Exclude rolling periods from calendar-month slots."""
        now = dt.datetime(2026, 4, 3, tzinfo=dt.UTC)

        def read(_title: str, boundary: dt.datetime) -> str:
            """Return a calendar report or a rolling report.

            Returns:
                Synthetic source at the requested publication cutoff.
            """
            if boundary.month == 2:
                return _popular("2026-01-01", "2026-01-31", "monthly")
            return _popular("2026-02-02", "2026-03-01", "monthly")

        data = collect_popularity(read, Issue(2027, 1), now)
        assert data["monthly_popularity"] == [
            {
                "month": 1,
                "days": 31,
                "title": "Game",
                "views": 31000,
            },
        ]

    @staticmethod
    def test_january_revisits_delayed_year_end_source() -> None:
        """Find a delayed year-end report captured on January 3."""
        now = dt.datetime(2027, 1, 4, tzinfo=dt.UTC)

        def read(_title: str, boundary: dt.datetime) -> str:
            """Expose a delayed report at its actual capture.

            Returns:
                A rolling report or the exact reviewed calendar year.
            """
            if boundary.date() == dt.date(2027, 1, 3):
                return _popular("2026-01-01", "2026-12-31")
            return _popular("2026-01-02", "2027-01-01")

        data = collect_popularity(read, Issue(2027, 1), now)
        assert data["annual_popularity"]["start"] == "2026-01-01"
        assert not data["annual_popularity"]["provisional"]

    @staticmethod
    def test_audited_quality_history_and_current_schema() -> None:
        """Exclude non-articles from annual assessment charts."""
        rows = quality_statistics(
            pl.DataFrame({
                "page_namespace": [0, 0, 14],
                "pa_class": ["优良", "小作品", "分类"],
            }),
            2026,
            complete=False,
        )
        assert sum(rows[0]["counts"].values()) == 11952
        assert sum(rows[1]["counts"].values()) == 12497
        assert rows[-1]["counts"]["ga"] == 1
        assert rows[-1]["counts"]["stub"] == 1
        assert sum(rows[-1]["counts"].values()) == 2
        assert rows[-1]["provisional"]

    @staticmethod
    def test_annual_prose_charts_rankings_and_award_summary() -> None:
        """Keep year-only popularity prose and inline cutoff notices."""
        popularity = parse_popularity(
            _popular("2026-01-01", "2026-10-31"),
            "yearly",
        )
        popularity["provisional"] = True
        review = _with_dyk_series({
            "overview": {"total": 13000},
            "previous_overview": {"total": 12497},
            "quality_statistics": quality_statistics(
                pl.DataFrame({
                    "pa_class": ["FA"] * 25,
                    "page_namespace": [0] * 25,
                }),
                2026,
                complete=False,
            ),
            "complete": False,
            "observation_end": "2026-11-01",
            "dyk_new_quarters": [
                {"date": "2026-03-31", "count": 20},
                {"date": "2026-06-30", "count": 40},
                {"date": "2026-09-30", "count": 60},
            ],
            "monthly_popularity": [
                {
                    "month": 1,
                    "days": 31,
                    "title": "Game",
                    "views": 31000,
                    "revision_id": 123456789,
                },
            ],
            "annual_popularity": popularity,
            "revision_ranking": [{"title": "Game", "revisions": 123}],
            "awards": [{"user": "New", "gained": 12, "total": 12}],
            "newcomers": ["New"],
        })
        text = render_annual_feature(Issue(2027, 1), review)
        assert "較去年年末的12,497篇淨增長503篇，日均淨增長1.65篇" in text
        assert "{{Memo|截至2026年10月31日|inline:info}}" in text
        assert "以下列出2026年瀏覽量最多的條目，至多25篇" in text
        assert "2025-11-01至2026-10-31統計期間內" not in text
        assert "暫定" not in text
        assert "# [[:Game]]：123笔修订" in text
        assert "年内共有1名编辑获得ACG专题奖得分。其中1名編者首次得分" in text
        assert "1名首次達到10分。" in text
        assert text.count("{{Graph:Chart") == 2
        assert text.count("See [[toolforge:aranami]]") == 2
        assert "WPVG Newsletter 202701 Feature Graph 2" in text
        assert "WPVG Newsletter 202701 Feature Graph 3" in text
        assert "WPVG Newsletter 202601 Feature Graph 3" in text
        assert "WPVG Newsletter 202501" not in text
        assert '<svg xmlns="http://www.w3.org/2000/svg"' not in text
        assert "歷年資料來源" not in text
        assert "! 年份 !! 新增优良条目" not in text
        assert "! 日期 !! 累计新条目推荐" not in text
        chart = annual_figures(review, 2026)[2]
        assert chart.axis[-4:] == (
            "2025-12-31",
            "2026-03-31",
            "2026-06-30",
            "2026-09-30",
        )
        assert "2026-10-31" not in chart.axis
        assert chart.series[0].counts[-5:] == (1323, 1360, 1380, 1400, 1420)
        assert "! 品質 !!" not in text
        assert "2025年年终条目品质概况" in text
        assert "2026年年终条目品质概况" in text
        assert "总浏览量为3,660万" in text
        assert "[[:Special:PermaLink/123456789#月瀏覽量|1月]]" in text
        assert "* 2月：" in text
        assert "|thumb|right|upright=1.4|" in text


class AnnualFigureIntroductionTests(TestCase):
    """Keep notices in the prose before annual lists and figures."""

    @staticmethod
    def test_pie_pair_follows_one_inline_notice() -> None:
        """Keep the paired figures in one grid after their notice."""
        code = mwparserfromhell.parse(
            render_annual_feature(Issue(2027, 1), _partial_annual_review()),
        )
        grid = next(
            tag
            for tag in code.filter_tags(recursive=False)
            if tag.tag == "div" and "display: grid" in str(tag)
        )
        charts = [
            template
            for template in grid.contents.filter_templates()
            if template.name.matches("File2")
        ]
        picture = mwparserfromhell.parse(
            str(grid.contents.filter_comments()[0].contents),
        ).filter_templates()[0]
        assert len(charts) == 1
        assert any(
            template.name.matches("Graph:Chart")
            for template in grid.contents.filter_templates()
        )
        for chart, issue in ((picture, 202701), (charts[0], 202601)):
            for variant in ("zh-cn", "zh-hk", "zh-tw"):
                assert chart.get(variant).value == (
                    f"WPVG Newsletter {issue} Feature Graph 3 ({variant}).png"
                )
        introduction = _preceding_introduction(code, grid)
        assert "各年度條目品質分布如下：" in introduction
        notices = mwparserfromhell.parse(introduction).filter_templates()
        assert len(notices) == 1
        assert notices[0].name.matches("Memo")
        assert notices[0].get("1").value == "截至2026年10月31日"
        assert notices[0].get("2").value == "inline:info"
        assert introduction.startswith(str(notices[0]))
        assert introduction.endswith("各年度條目品質分布如下：")

    def test_each_block_has_its_notice_in_the_immediate_introduction(
        self,
    ) -> None:
        """Date each block before it using that observation's cutoff."""
        text = render_annual_feature(Issue(2027, 1), _partial_annual_review())
        sections = {
            name: mwparserfromhell.parse(
                text.partition(f"==== {name} ====")[2].partition(
                    "==== ",
                )[0],
            )
            for name in ("內容評審", "新章推薦", "条目报告", "榮譽表彰")
        }
        quality = sections["內容評審"]
        dyk = sections["新章推薦"]
        articles = sections["条目报告"]
        awards = sections["榮譽表彰"]
        quality_blocks = quality.filter_tags(recursive=False)
        columns = [
            template
            for template in articles.filter_templates(recursive=False)
            if template.name.matches("div col")
        ]
        blocks = (
            (
                quality,
                next(tag for tag in quality_blocks if tag.tag == "div"),
                "歷年高品質條目入選數量如下：",
                "2026年10月31日",
            ),
            (
                quality,
                next(tag for tag in quality_blocks if tag.tag == "li"),
                "新入選或晉級條目如下：",
                "2026年10月31日",
            ),
            (
                quality,
                next(tag for tag in quality_blocks if tag.tag == "table"),
                "作者名單如下：",
                "2026年10月31日",
            ),
            (
                dyk,
                next(
                    tag
                    for tag in dyk.filter_tags(recursive=False)
                    if tag.tag == "li"
                ),
                "本年度新條目推薦名單如下：",
                "2026年10月31日",
            ),
            (
                articles,
                columns[0],
                "以下列出2026年各月日均瀏覽量最高的條目：",
                "2026年10月31日",
            ),
            (
                articles,
                columns[1],
                "以下列出2026年瀏覽量最多的條目",
                "2026年10月31日",
            ),
            (
                articles,
                columns[2],
                "以修訂次數統計，以下列出本年度排名前25名的條目：",
                "2026年10月31日",
            ),
            (
                awards,
                next(
                    template
                    for template in awards.filter_templates(recursive=False)
                    if template.name.matches("div col")
                ),
                "ACG專題獎年度得分",
                "2026年10月31日",
            ),
        )
        for code, node, sentence, date in blocks:
            with self.subTest(introduction=sentence):
                introduction = _preceding_introduction(code, node)
                assert introduction.startswith(
                    f"{{{{Memo|截至{date}|inline:info}}}}" + sentence,
                )
                notices = [
                    template
                    for template in mwparserfromhell.parse(
                        introduction,
                    ).filter_templates()
                    if template.name.matches("Memo")
                ]
                assert notices
                assert any(
                    date in str(notice.get("1").value) for notice in notices
                )
                assert all(
                    notice.get("2").value == "inline:info"
                    for notice in notices
                )
        popularity_intro = _preceding_introduction(articles, columns[1])
        assert "以下列出2026年瀏覽量最多的條目" in popularity_intro
        assert "2025-11-01至2026-10-31統計期間內" not in popularity_intro
        assert "歷年新條目推薦累計數量如下：" not in text
        dyk_chart = next(
            template
            for template in dyk.filter_templates(recursive=False)
            if template.name.matches("Image frame")
        )
        assert str(dyk_chart.get("caption").value).strip() == (
            "{{Memo|截至2026年9月30日|inline:info}}"
            "电子游戏专题累计新条目推荐数量"
        )
        revision_tail = str(articles).partition("[[:Revised]]")[2]
        assert not any(
            template.name.matches("Memo")
            for template in mwparserfromhell.parse(
                revision_tail,
            ).filter_templates()
        )
