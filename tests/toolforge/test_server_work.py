"""Verify the Hub and Web share the fixed server metrics table."""

from __future__ import annotations

import copy
import datetime as dt
from unittest import TestCase

from status_fixtures import active_collection_record, status_snapshot

from webservice.pages import render_about, render_live_status
from webservice.presentation import Interface
from webservice.status_view import status_context


class ServerColumnsTests(TestCase):
    """Render independent observations in full and live fragments."""

    @staticmethod
    def test_server_columns_and_dataset_sections() -> None:
        """Keep service metrics and dataset updates independent."""
        status = status_snapshot()
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
                assert 'server-metrics" data-no-pagination' in output
                for service in ("hub", "web"):
                    name = interface.text(f"server.{service}")
                    assert f'<th scope="col">{name}</th>' in output
                assert 'id="server-work"' not in output
                assert 'id="dataset-updates-previous"' in output
                assert 'id="dataset-updates-current"' in output

    @staticmethod
    def test_web_measurements_expire_independently_of_the_hub() -> None:
        """Keep Web CPU current when the Hub heartbeat is stale."""
        status = status_snapshot()
        hub = status["services"]["scheduler"]
        web = copy.deepcopy(hub)
        web["resources"]["cpu_percent"] = 12.5
        web["heartbeat_at"] = "2026-10-18T12:00:25Z"
        status["services"]["web"] = web
        hub["freshness"] = "stale"
        rows = status_context(
            Interface("en"),
            status,
            "1.0.0a1",
            dt.datetime(2026, 10, 18, 12, 0, 30, tzinfo=dt.UTC),
        )["server"]["rows"]
        hub_cpu, web_cpu = next(
            row["cells"] for row in rows if row["key"] == "cpu"
        )
        assert hub_cpu["expires"] is None
        assert web_cpu["expires"] == "2026-10-18T12:01:55+00:00"
        assert web_cpu["value"] == "0.125 cores / 2 cores"
