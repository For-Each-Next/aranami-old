"""Verify the jobs table before schedules are available."""

from __future__ import annotations

import datetime as dt
from unittest import TestCase

from status_fixtures import active_collection_record, status_snapshot

from webservice.pages import (
    render_about,
    render_live_status,
    render_live_update,
)
from webservice.presentation import Interface
from webservice.status_view import status_context


class ServerJobsTests(TestCase):
    """Render independent observations in full and live fragments."""

    @staticmethod
    def test_web_job_without_saved_schedules() -> None:
        """Show the observed web job before scheduled jobs are known."""
        status = status_snapshot()
        status["services"]["web"] = {
            **status["services"]["scheduler"],
            "service_id": "web",
            "schedules": {},
        }
        running = active_collection_record("website", 50)
        status["executions"][running["run_id"]] = running
        now = dt.datetime(2026, 10, 18, 12, 0, 30, tzinfo=dt.UTC)
        config = {"version": "1.0.0a1"}
        for locale in ("en", "zh-hans", "zh-hant"):
            interface = Interface(locale)
            for output in (
                render_about(config, locale, status=status, now=now),
                render_live_status(status, config, locale, now),
            ):
                assert 'server-jobs" data-no-pagination' in output
                for key in ("job", "job_type", "state", "memory", "cpu"):
                    name = interface.text(f"server.{key}")
                    assert f'<th scope="col">{name}</th>' in output
                assert ">aranami-web</th>" in output
                assert "server-metrics" not in output
                assert "100.0 MiB / 4.0 GiB" in output
                assert 'id="server-work"' not in output
                assert 'id="dataset-updates-previous"' in output
                assert 'id="dataset-updates-current"' in output
            live = render_live_update(status, config, locale)["html"]
            assert 'server-jobs" data-no-pagination' in live
            assert ">aranami-web</th>" in live
            assert "server-metrics" not in live

    @staticmethod
    def test_web_measurements_follow_the_web_heartbeat() -> None:
        """Distinguish missing usage, zero, and cached allocation."""
        status = status_snapshot()
        web = status["services"].pop("scheduler")
        web["service_id"] = "web"
        web["heartbeat_at"] = "2026-10-18T12:00:25Z"
        status["services"]["web"] = web
        now = dt.datetime(2026, 10, 18, 12, 0, 30, tzinfo=dt.UTC)
        interface = Interface("en")
        for percent, expected in ((0, "0"), (0.3, "0.003"), (12.5, "0.125")):
            web["resources"].update(cpu_percent=percent, memory_bytes=0)
            (job,) = status_context(interface, status, "1.0.0a1", now)[
                "server"
            ]["jobs"]
            assert job["expires"] == "2026-10-18T12:01:55+00:00"
            assert job["usage"]["cpu"] == f"{expected} cores / 2 cores"
            assert job["usage"]["memory"] == "0 B / 4.0 GiB"
        web["freshness"] = "stale"
        (job,) = status_context(interface, status, "1.0.0a1", now)["server"][
            "jobs"
        ]
        assert job["expires"] is None
        assert job["status"] == interface.text("server.job_unknown")
        assert job["usage"] == {
            "memory": "Not recorded / 4.0 GiB",
            "cpu": "Not recorded / 2 cores",
        }
