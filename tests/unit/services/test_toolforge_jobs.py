"""Verify grouped manifests, source handoffs and independent retries."""

# ruff: file-ignore[pytest-unittest-raises-assertion]

import datetime as dt
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from data.collection_leases import collection_lease
from data.runtime.status import read_status
from runtime.services import hourly
from shared.config import TASK_DEFINITIONS
from shared.toolforge.jobs import (
    ARTICLE_STATISTICS,
    DATA_FETCH,
    JOB_DEFINITIONS,
    MAINTENANCE,
    PROJECT_SNAPSHOT,
    REPORT_UPDATE,
    SERVICES,
    WEB_MEMORY,
    WORKLOAD_SERVICES,
    job_definitions,
    job_name,
    save_installed_schedules,
)
from shared.toolforge.state import (
    ACTIVE_PATH,
    GROUPED_PATH,
    completed,
    fetch_outcome,
    hour,
    record_completion,
    record_fetch,
)


class TestJobDefinitions(TestCase):
    """Cover grouped workload ownership and planned memory use."""

    @staticmethod
    def test_grouped_manifest() -> None:
        """Check the three schedules and optional definitions."""
        root = Path("/data/project/aranami")
        definitions = job_definitions(root)
        assert {row["name"] for row in definitions} == {
            "aranami-web",
            *map(job_name, SERVICES),
        }
        assert definitions[0]["continuous"] is True
        assert definitions[1]["schedule"] == "0 * * * *"
        assert JOB_DEFINITIONS.keys() <= WORKLOAD_SERVICES.keys()
        extended = job_definitions(
            root,
            on_demand=True,
            weekly_maintenance=True,
        )
        assert extended[-2]["name"] == job_name(ARTICLE_STATISTICS)
        assert "schedule" not in extended[-2]
        assert extended[-1]["name"] == job_name(MAINTENANCE)
        assert extended[-1]["schedule"] == "40 3 * * 0"

    @staticmethod
    def test_promotion_headroom() -> None:
        """Fit the jobs and setup worker in the live quota."""
        quota_mib = 8192
        assert (
            WEB_MEMORY + sum(w.memory for w in SERVICES.values()) + 1536 + 512
            <= quota_mib
        )


class TestHandoff(TestCase):
    """Simulate scheduled phases without any wiki requests."""

    def setUp(self) -> None:
        """Select an isolated runtime and a fixed UTC hour."""
        self.runtime = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.enterContext(chdir(self.runtime))
        self.now = dt.datetime(2026, 11, 21, 0, 12, tzinfo=dt.UTC)
        self.cycle = hour(self.now)
        clock = mock.Mock(wraps=dt)
        clock.datetime.now.return_value = self.now
        self.enterContext(mock.patch.object(hourly, "dt", clock))
        self.worker = self.enterContext(
            mock.patch.object(hourly, "_run_child"),
        )

    @staticmethod
    def enable() -> None:
        """Enable only the new schedules."""
        ACTIVE_PATH.parent.mkdir(parents=True)
        ACTIVE_PATH.touch()
        GROUPED_PATH.touch()

    def test_paused_services_make_no_requests(self) -> None:
        """Staged CronJobs cannot dispatch while admission is paused."""
        hourly.run_service(PROJECT_SNAPSHOT)
        self.worker.assert_not_called()

    def test_live_owner_is_exclusive(self) -> None:
        """Skip a launch while another worker owns the service."""
        self.enable()
        with collection_lease(
            self.runtime,
            f"{PROJECT_SNAPSHOT}-service",
        ) as acquired:
            assert acquired
            hourly.run_service(PROJECT_SNAPSHOT)
        self.worker.assert_not_called()

    def test_fetch_and_analysis_follow_the_same_hour(self) -> None:
        """Release analysis after the source status commits."""
        self.enable()
        hourly.run_service(PROJECT_SNAPSHOT)
        hourly.run_service(DATA_FETCH)
        assert fetch_outcome(self.runtime, self.cycle) == "succeeded"
        hourly.run_service(REPORT_UPDATE)
        phases = [call.args[:2] for call in self.worker.call_args_list]
        assert phases[0] == ("fetch", PROJECT_SNAPSHOT)
        assert all(("fetch", task) in phases for task in TASK_DEFINITIONS)
        assert phases.index(("fetch", "dyks")) < phases.index((
            "analyze",
            "dyks",
        ))
        assert completed(self.runtime, REPORT_UPDATE, self.cycle)

    def test_daily_failure_retries_and_preserves_success(self) -> None:
        """Retry failed daily output while preserving successes."""
        self.enable()
        hourly.run_service(PROJECT_SNAPSHOT)
        hourly.run_service(DATA_FETCH)

        def analyze(phase: str, name: str, *_args: object) -> None:
            """Fail a single workload.

            Raises:
                OSError: The assessment list publication is unavailable.
            """
            if phase == "analyze" and name == "assessment_lists":
                message = "Publication unavailable"
                raise OSError(message)

        self.worker.side_effect = analyze
        with self.assertRaises(RuntimeError):
            hourly.run_service(REPORT_UPDATE)
        assert not completed(self.runtime, "assessment_lists", self.cycle)
        assert completed(self.runtime, "assessment_log", self.cycle)
        self.worker.reset_mock(side_effect=True)
        hourly.run_service(REPORT_UPDATE)
        calls = [call.args[:2] for call in self.worker.call_args_list]
        assert ("analyze", "assessment_lists") in calls
        assert ("analyze", "assessment_log") not in calls

    def test_stale_fetch_cannot_release_analysis(self) -> None:
        """Wait for this hour even when the prior hour succeeded."""
        self.enable()
        record_completion(self.runtime, PROJECT_SNAPSHOT, self.cycle)
        record_fetch(
            self.runtime,
            self.cycle - dt.timedelta(hours=1),
            "succeeded",
        )
        with (
            mock.patch.object(hourly, "sleep", side_effect=TimeoutError),
            self.assertRaises(TimeoutError),
        ):
            hourly.run_service(REPORT_UPDATE)
        self.worker.assert_not_called()

    def test_installed_schedules_show_grouped_owners(self) -> None:
        """Represent installed CronJobs in the public plan."""
        self.enable()
        items = [
            {
                "metadata": {"name": row["name"]},
                "spec": {"schedule": row["schedule"]},
            }
            for row in job_definitions(self.runtime)
            if "schedule" in row
        ]
        save_installed_schedules(self.runtime, {"items": items})
        plan = read_status(self.runtime, as_of=self.now)["toolforge_schedules"]
        assert set(plan["services"]) == set(SERVICES)
        assert plan["routines"]["dyks"]["job_name"] == job_name(REPORT_UPDATE)
        assert plan["collections"]["newsletter-history"][
            "job_name"
        ] == job_name(DATA_FETCH)
