"""Verify independent dataset-update lists and their live fragments."""

# Displayed table dimensions use multiplication signs.
# ruff: file-ignore[ambiguous-unicode-character-string]

from __future__ import annotations

import copy
import datetime as dt
import re
from unittest import TestCase
from unittest.mock import patch

from status_fixtures import status_snapshot

from webservice.dataset_updates import dataset_updates_context, with_card_ids
from webservice.pages import render_about, render_live_status
from webservice.presentation import Interface
from webservice.status_view import status_context

_NOW = dt.datetime(2026, 11, 14, 12, 0, 30, tzinfo=dt.UTC)


def _updates() -> dict:
    """Provide completed, failed and active files with saved evidence.

    Returns:
        The presentation contract, independent of storage acquisition.
    """
    started = {
        "known": True,
        "value": "2026-11-14T12:00:00Z",
        "label": "2026-11-14 12:00:00",
    }
    baseline = {
        "filename": "old.parquet",
        "url": "/data/?file=data/raw/old.parquet&page=1&lang=en",
        "shape": "12 × 3",
    }
    completed = {
        "key": "previous-file",
        "filename": "new<unsafe>.parquet",
        "url": "/data/?file=data/raw/new.parquet&page=1&lang=en",
        "state": "succeeded",
        "started": started,
        "finished": {**started, "label": "2026-11-14 12:00:15"},
        "baseline": baseline,
        "shape": "14 × 4",
        "reports": [{"name": "Report <unsafe>", "url": "/reports/"}],
    }
    return {
        "previous": {
            "items": [
                completed,
                {
                    **completed,
                    "key": "failed-file",
                    "filename": "failed.parquet",
                    "state": "failed",
                    "shape": None,
                },
            ],
        },
        "current": {
            "state": "running",
            "scheduled": started,
            "items": [
                {
                    "key": "next-file",
                    "filename": "next.parquet",
                    "state": "running",
                    "started": started,
                    "baseline": baseline,
                    "elapsed": {
                        "running": True,
                        "started": started["value"],
                        "label": "0:30.00",
                    },
                    "activity": "Reading <source>",
                    "reports": [{"name": "Report <unsafe>", "url": None}],
                },
            ],
        },
        "expires": "2026-11-14T12:01:30Z",
    }


def _render_updates(data: dict, locale: str, *, live: bool = False) -> str:
    """Render controlled update evidence through page templates.

    Returns:
        A full About document or the WebSocket HTML fragments.
    """

    def context(*args: object, **kwargs: object) -> dict:
        """Inject the dataset presentation contract.

        Returns:
            Ordinary status with controlled dataset evidence.
        """
        result = status_context(*args, **kwargs)
        updates = copy.deepcopy(data)
        for section in ("current", "previous"):
            if section in updates:
                updates[section]["items"] = with_card_ids(
                    updates[section]["items"],
                    section,
                )
        result["server"]["dataset_updates"] = updates
        return result

    config = {"version": "0.9.15"}
    with patch("webservice.pages.status_context", side_effect=context):
        if live:
            return render_live_status(status_snapshot(), config, locale, _NOW)
        return render_about(config, locale, status=status_snapshot(), now=_NOW)


class DatasetUpdatePresentationTests(TestCase):
    """Keep dataset evidence in separate semantic sections."""

    @staticmethod
    def test_lists_and_fragments_match_in_all_locales() -> None:
        """Use the same escaped evidence in full and pushed pages."""
        for locale in ("en", "zh-hans", "zh-hant"):
            full = _render_updates(_updates(), locale)
            live = _render_updates(_updates(), locale, live=True)
            for kind in ("previous", "current"):
                pattern = rf'<section id="dataset-updates-{kind}".*?</section>'
                first = re.search(pattern, full, re.DOTALL)
                second = re.search(pattern, live, re.DOTALL)
                assert first is not None
                assert second is not None
                assert first[0] == second[0]
                assert "<h2 " in first[0]
                assert re.search(
                    r'aria-controls="(dataset-job-[a-f0-9]+)"'
                    r'.*<dialog id="\1"',
                    first[0],
                    re.DOTALL,
                )
            assert 'id="server-work"' not in full
            assert "new&lt;unsafe&gt;.parquet</a></h3>" in full
            assert "new<unsafe>.parquet" not in full
            assert "Report &lt;unsafe&gt;" in full
            assert "14 × 4" in full
            for icon in ("✅", "❌", "⌛"):
                assert icon in full
            assert "next.parquet</a></h3>" in full
            assert "data-dataset-link" in full
            assert 'data-clock="dataset-elapsed"' in full
            assert "Reading &lt;source&gt;" in full
            assert "2026-11-14 12:00:15</time> UTC" in full
            assert Interface(locale).text("dataset_updates.running") in full

    @staticmethod
    def test_plans_do_not_claim_running_or_start_a_clock() -> None:
        """Offer planned job details without an elapsed clock."""
        data = _updates()
        data["current"]["state"] = "planned"
        item = data["current"]["items"][0]
        item.update(state="pending", started=None, elapsed=None, activity=None)
        output = _render_updates(data, "zh-hans")
        assert "更新排程</h2>" in output
        assert "正在更新资料" not in output
        assert 'data-clock="dataset-elapsed"' not in output
        assert "next.parquet</a></h3>" in output
        assert 'href="/data/?file=data/raw/next.parquet' not in output

    @staticmethod
    def test_empty_evidence_is_explicit() -> None:
        """Render missing records without inventing successful files."""
        output = _render_updates({}, "en")
        assert Interface("en").text("dataset_updates.no_previous") in output
        assert Interface("en").text("dataset_updates.no_planned") in output
        assert 'class="dataset-update-files"' not in output


class DatasetUpdateContextTests(TestCase):
    """Verify time windows and independently owned collectors."""

    def setUp(self) -> None:
        """Prepare current scheduler observations."""
        self.interface = Interface("en")
        self.status = {
            "services": {
                "scheduler": {
                    "freshness": "current",
                    "lifecycle": "running",
                    "boot_id": "1" * 32,
                    "heartbeat_at": _NOW.isoformat(),
                    "schedules": {"collections": {}},
                },
            },
            "executions": {},
            "dataset_updates": {"tasks": {}},
        }

    def context(self, now: dt.datetime = _NOW) -> dict:
        """Read the pure presentation at a controlled clock.

        Returns:
            Localized observed outcomes and scheduled work.
        """
        return dataset_updates_context(self.interface, self.status, now)

    def test_manual_collector_runs_without_scheduler_ownership(self) -> None:
        """Show manual activity before it opens any output file."""
        self.status["services"]["scheduler"]["freshness"] = "stale"
        self.status["executions"]["a" * 32] = {
            "run_id": "a" * 32,
            "boot_id": "2" * 32,
            "task_id": "quality-authorship",
            "kind": "collection",
            "outcome": "running",
            "started_at": _NOW.isoformat(),
            "updated_at": _NOW.isoformat(),
            "finished_at": None,
            "progress": {"phase": "preparing"},
        }
        result = self.context()
        assert result["current"]["state"] == "running"
        (item,) = result["current"]["items"]
        assert item["is_task"]
        assert item["elapsed"]["running"]
        assert item["started"]["known"]
        stale = self.context(_NOW + dt.timedelta(seconds=91))
        assert stale["current"]["state"] == "unavailable"
        assert stale["current"]["items"] == []

    def test_next_hour_contains_all_collectors_and_queued_work(self) -> None:
        """Include the hourly boundary and exclude later work."""
        schedules = self.status["services"]["scheduler"]["schedules"][
            "collections"
        ]
        for task, offset in [
            ("website", 10),
            ("quality-analysis", 60),
            ("quality-authorship", 61),
        ]:
            schedules[task] = {
                "state": "scheduled",
                "next_run_at": (
                    _NOW + dt.timedelta(minutes=offset)
                ).isoformat(),
            }
        schedules["newsletter-history"] = {
            "state": "scheduled",
            "queued_since": (_NOW - dt.timedelta(minutes=2)).isoformat(),
            "next_run_at": (_NOW + dt.timedelta(hours=2)).isoformat(),
        }
        result = self.context()
        keys = {item["key"] for item in result["current"]["items"]}
        assert keys == {
            "task:website",
            "task:quality-analysis",
            "task:newsletter-history",
        }
        assert all(
            item["scheduled"]["known"] for item in result["current"]["items"]
        )
        assert not any(
            item["elapsed"]["running"] for item in result["current"]["items"]
        )

    def test_previous_results_expire_after_two_hours_and_deduplicate(
        self,
    ) -> None:
        """Keep recent outcomes by actual file finish, even mid-run."""

        def row(name: str, age: dt.timedelta) -> dict:
            """Prepare an observed completed file.

            Returns:
                A safe row with known acquisition timestamps.
            """
            return {
                "filename": "data/raw/" + name + ".parquet",
                "state": "succeeded",
                "started_at": _NOW.isoformat(),
                "finished_at": (_NOW - age).isoformat(),
            }

        self.status["dataset_updates"]["tasks"]["website"] = {
            "current": {
                "run_id": "a" * 32,
                "files": {
                    "boundary": row("boundary", dt.timedelta(hours=2)),
                    "old": row("old", dt.timedelta(hours=2, microseconds=1)),
                    "recent": row("same", dt.timedelta(minutes=1)),
                },
            },
            "previous": {
                "run_id": "b" * 32,
                "files": {
                    "earlier": row("same", dt.timedelta(minutes=2)),
                },
            },
        }
        items = self.context()["previous"]["items"]
        assert [item["filename"] for item in items] == [
            "data/raw/same.parquet",
            "data/raw/boundary.parquet",
        ]
        assert (
            items[0]["finished"]["value"]
            == (_NOW - dt.timedelta(minutes=1)).isoformat()
        )

    def test_rotated_recent_file_remains_visible(self) -> None:
        """Read retained results after both task slots have rotated."""
        self.status["dataset_updates"]["recent"] = [
            {
                "run_id": "a" * 32,
                "task_id": "quality-analysis",
                "file": {
                    "filename": "data/raw/retained.parquet",
                    "state": "succeeded",
                    "started_at": _NOW.isoformat(),
                    "finished_at": _NOW.isoformat(),
                },
            },
        ]
        (item,) = self.context()["previous"]["items"]
        assert item["filename"] == "data/raw/retained.parquet"

    def test_native_sections_include_schedules_and_run_outcomes(self) -> None:
        """Use installed jobs and preserve their file observations."""
        self.status["toolforge_schedules"] = {
            "active_since": (_NOW - dt.timedelta(hours=1)).isoformat(),
            "collections": {},
            "routines": {
                "pexbot": {
                    "job_name": "aranami-pexbot",
                    "state": "scheduled",
                    "next_run_at": (_NOW + dt.timedelta(hours=8)).isoformat(),
                    "cron": "23 20 * * *",
                },
            },
        }
        run_id = "a" * 32
        self.status["executions"][run_id] = {
            "run_id": run_id,
            "task_id": "quality-authorship",
            "trigger": "scheduled",
            "kind": "collection",
            "outcome": "failed",
            "started_at": (_NOW - dt.timedelta(minutes=2)).isoformat(),
            "finished_at": _NOW.isoformat(),
        }
        self.status["dataset_updates"]["recent"] = [
            {
                "run_id": run_id,
                "file": {
                    "filename": (
                        "data/parsed/authorship--g-20261114120000--targets.parquet"
                    ),
                    "state": "succeeded",
                    "available": True,
                    "finished_at": _NOW.isoformat(),
                },
            },
        ]
        result = self.context()
        (scheduled,) = result["current"]["items"]
        assert scheduled["job_name"] == "aranami-pexbot"
        assert scheduled["scheduled"]["known"]
        (recent,) = result["previous"]["items"]
        assert recent["job_name"] == "aranami-quality-authorship"
        assert recent["state"] == "failed"
        assert recent["files"][0]["state"] == "succeeded"
        rendered = _render_updates(result, "en")
        assert self.interface.text("routine.pexbot") + "</a></h3>" in rendered
        assert self.interface.text("routine.quality-authorship") in rendered
        assert "<code>aranami-pexbot</code>" in rendered
        assert "<h4>Dataset files</h4>" in rendered

    @staticmethod
    def test_job_table_shows_toolforge_names_status_and_usage() -> None:
        """Show installed jobs with current usage and allocation."""
        status = status_snapshot()
        status["toolforge_schedules"] = {
            "active_since": (_NOW - dt.timedelta(hours=1)).isoformat(),
            "routines": {},
            "collections": {},
            "services": {
                "project-data": {
                    "job_name": "aranami-project-data",
                    "state": "scheduled",
                    "next_run_at": (_NOW + dt.timedelta(hours=1)).isoformat(),
                    "cron": "0 * * * *",
                    "memory_limit_bytes": 1024**3,
                    "cpu_limit": 1,
                },
                "pageviews": {
                    "job_name": "aranami-pageviews",
                    "state": "scheduled",
                    "next_run_at": _NOW.replace(
                        hour=19,
                        minute=0,
                        second=0,
                    ).isoformat(),
                    "cron": "0 * * * *",
                    "memory_limit_bytes": 2 * 1024**3,
                    "cpu_limit": 2,
                },
            },
        }
        running = {
            "started_at": (_NOW - dt.timedelta(seconds=10)).isoformat(),
            "observed_at": _NOW.isoformat(),
            "expires_at": (_NOW + dt.timedelta(seconds=35)).isoformat(),
            "outcome": "running",
            "resources": {"cpu_percent": 3, "memory_bytes": 768 * 1024**2},
        }
        status["toolforge_samples"] = {
            "project-data": running,
            "article-statistics": running,
            "pageviews": {
                "started_at": (_NOW - dt.timedelta(minutes=4)).isoformat(),
                "observed_at": (_NOW - dt.timedelta(minutes=3)).isoformat(),
                "expires_at": None,
                "outcome": "succeeded",
                "resources": {},
            },
        }
        config = {"version": "0.10.0.dev9"}
        for output in (
            render_about(config, "zh-hans", status=status, now=_NOW),
            render_live_status(status, config, "zh-hans", _NOW),
        ):
            assert 'class="ui-table__table server-jobs"' in output
            assert '<th scope="col">作业名称</th>' in output
            assert 'title="网页服务">aranami-web</th>' in output
            assert ">aranami-project-data</th>" in output
            assert ">aranami-article-statistics</th>" in output
            assert '<td title="0 * * * *">每小时第 00 分</td>' in output
            assert "每天 19:00，失败后每小时重试" in output
            assert "<td>一次性</td>" in output
            assert "已运行 10秒" in output
            assert "已等待 3分0秒" in output
            assert "0.03 核心 / 1 核心" in output
            assert "768.0 MiB / 1.0 GiB" in output
            assert "未记录 / 2.0 GiB" in output

        expired = status_context(
            Interface("en"),
            status,
            config["version"],
            _NOW + dt.timedelta(seconds=35),
        )["server"]["jobs"]
        project = next(
            row for row in expired if row["key"] == "aranami-project-data"
        )
        assert project["status"] == "Unknown"
        assert project["usage"] == project["idle_usage"]
