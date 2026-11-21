"""Verify Toolforge definitions and the saved data handoff."""

# ruff: file-ignore[pytest-unittest-raises-assertion]

import datetime as dt
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from data.collection_leases import collection_lease
from data.runtime.status import read_status
from runtime import toolforge_job
from shared.toolforge_jobs import (
    ACTIVE_PATH,
    ALLOCATIONS,
    JOB_DEFINITIONS,
    WEB_CPU,
    WEB_MEMORY,
    job_definitions,
    job_name,
)


class TestJobDefinitions(TestCase):
    """Cover the workloads and measure planned quota usage."""

    @staticmethod
    def test_definitions_cover_all_workloads() -> None:
        """Expose unique names and preserve the data boundary."""
        definitions = job_definitions(Path("/data/project/aranami"))
        assert ALLOCATIONS.keys() == JOB_DEFINITIONS.keys()
        assert {row["name"] for row in definitions} == {
            "aranami-web",
            *map(job_name, JOB_DEFINITIONS),
        }
        assert len(definitions) == len(JOB_DEFINITIONS) + 1
        assert [row["name"] for row in definitions if "publish" in row] == [
            "aranami-web",
        ]
        assert definitions[1]["schedule"] == "0 * * * *"

    @staticmethod
    def test_allocations_leave_promotion_headroom() -> None:
        """Budget an extra web pod and the default setup one-off."""
        max_pods, max_memory_mib, max_cpu_millicores = 10, 8192, 2000
        for hour in range(24):
            for minute in range(60):
                active = [
                    limits
                    for name, limits in ALLOCATIONS.items()
                    if JOB_DEFINITIONS[name].hour in {"*", str(hour)}
                    and limits.minute
                    <= minute
                    < limits.minute + limits.minutes
                ]
                assert 3 + len(active) <= max_pods
                assert (
                    512
                    + 2 * WEB_MEMORY
                    + sum(limits.memory for limits in active)
                    <= max_memory_mib
                )
                assert (
                    100 + 2 * WEB_CPU + sum(limits.cpu for limits in active)
                    <= max_cpu_millicores
                )


class TestScheduledJob(TestCase):
    """Exercise the runner with fake acquisition and isolated files."""

    def setUp(self) -> None:
        """Create a tool directory and freeze its actual UTC clock."""
        self.runtime = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.enterContext(chdir(self.runtime))
        self.now = dt.datetime(2026, 11, 21, 0, 16, tzinfo=dt.UTC)
        clock = mock.Mock(wraps=dt)
        clock.datetime.now.return_value = self.now
        self.enterContext(mock.patch.object(toolforge_job, "dt", clock))
        self.execute = self.enterContext(
            mock.patch.object(toolforge_job, "_execute"),
        )

    @staticmethod
    def enable_jobs() -> None:
        """Enable the individual jobs in the test runtime."""
        ACTIVE_PATH.parent.mkdir(parents=True)
        ACTIVE_PATH.touch()

    def test_paused_jobs_make_no_source_calls(self) -> None:
        """A staged schedule cannot race the current live scheduler."""
        toolforge_job.run_job("project-data")
        self.execute.assert_not_called()

    def test_report_waits_for_current_input_and_owns_its_cycle(self) -> None:
        """Dispatch a report once its current inputs have committed."""
        self.enable_jobs()
        with (
            mock.patch.object(
                toolforge_job,
                "monotonic",
                side_effect=[0, 9999],
            ),
            self.assertRaises(TimeoutError),
        ):
            toolforge_job.run_job("assessment_log")
        self.execute.assert_not_called()
        toolforge_job.run_job("project-data")
        toolforge_job.run_job("assessment_log")
        toolforge_job.run_job("assessment_log")
        assert self.execute.call_args_list == [
            mock.call("project-data", self.now),
            mock.call("assessment_log", self.now),
        ]

    def test_failed_capture_does_not_release_consumers(self) -> None:
        """A failed collector leaves downstream reports waiting."""
        self.enable_jobs()
        self.execute.side_effect = OSError("failed source")
        with self.assertRaises(OSError):
            toolforge_job.run_job("project-data")
        assert not (ACTIVE_PATH.parent / "project-data.json").exists()

    def test_publishers_share_the_job_lease(self) -> None:
        """Skip another job invocation while its owner is live."""
        self.enable_jobs()
        with collection_lease(
            self.runtime,
            job_name("assessment_lists"),
        ) as held:
            assert held
            toolforge_job.run_job("assessment_lists")
        self.execute.assert_not_called()

    def test_configured_times_do_not_require_hub_heartbeat(self) -> None:
        """Report cron plans with ordinary status domains."""
        self.enable_jobs()
        status = read_status(self.runtime, as_of=self.now)
        assert not status["services"]
        jobs = status["toolforge_schedules"]
        assert jobs["collections"]["project-data"]["next_run_at"] == (
            "2026-11-21T01:00:00+00:00"
        )
        assert jobs["routines"]["assessment_lists"]["next_run_at"] == (
            "2026-11-21T00:17:00+00:00"
        )
