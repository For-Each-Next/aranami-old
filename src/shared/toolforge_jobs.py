"""Define Aranami's Toolforge jobs and initial allocations."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from shlex import quote

from shared.config import COLLECTION_DEFINITIONS, TASK_DEFINITIONS

STATE_DIRECTORY = Path("state/toolforge-jobs")
ACTIVE_PATH = STATE_DIRECTORY / "active"
JOB_DEFINITIONS = COLLECTION_DEFINITIONS | TASK_DEFINITIONS
_IMAGE = "python3.13"


@dataclass(frozen=True, slots=True)
class JobAllocation:
    """Describe the scheduled launch and resource limits of one worker.

    Attributes:
        minute: UTC launch minute after the nominal source boundary.
        minutes: Maximum wall time, including waits and retries.
        memory: Container memory limit in MiB.
        cpu: Container CPU limit in millicores.
    """

    minute: int
    minutes: int
    memory: int
    cpu: int


# Keep source boundaries at :00. Stagger consumers and bound their
# runtimes to leave room for the web pod and setup jobs.
ALLOCATIONS = {
    "project-data": JobAllocation(0, 8, 1536, 250),
    "newsletter-history": JobAllocation(2, 10, 1024, 200),
    "newsletter-daily": JobAllocation(6, 12, 2048, 250),
    "dyks": JobAllocation(9, 12, 512, 150),
    "new_pages": JobAllocation(12, 13, 768, 200),
    "assessment_log": JobAllocation(14, 10, 512, 150),
    "assessment_lists": JobAllocation(17, 9, 768, 150),
    "enwp_key_articles": JobAllocation(19, 10, 768, 200),
    "pageviews": JobAllocation(21, 12, 1536, 250),
    "pexbot": JobAllocation(23, 6, 512, 100),
    "website": JobAllocation(30, 11, 2048, 250),
    "quality-analysis": JobAllocation(42, 4, 1024, 200),
    "quality-authorship": JobAllocation(47, 11, 1536, 250),
}
WEB_MEMORY = 1024
WEB_CPU = 250


def next_launch(name: str, now: dt.datetime) -> dt.datetime:
    """Return the next configured UTC launch, independent of job health.

    Args:
        name: Configured report or collection identifier.
        now: Actual UTC observation time.

    Returns:
        The next cron boundary after the observation.
    """
    launch = now.replace(
        minute=ALLOCATIONS[name].minute,
        second=0,
        microsecond=0,
    )
    hour = JOB_DEFINITIONS[name].hour
    if hour == "*":
        return launch if launch > now else launch + dt.timedelta(hours=1)
    launch = launch.replace(hour=int(hour))
    return launch if launch > now else launch + dt.timedelta(days=1)


def job_name(name: str) -> str:
    """Return the Toolforge name for a configured workload.

    Args:
        name: Report or collection identifier.

    Returns:
        A DNS-compatible job name with the tool prefix.
    """
    return f"aranami-{name.replace('_', '-')}"


def job_definitions(runtime: Path) -> list[dict[str, object]]:
    """Generate a Jobs Framework configuration for this tool.

    Args:
        runtime: Shared tool directory containing the selected source.

    Returns:
        Public web and separately scheduled background job definitions.
    """
    scripts = runtime / "app/scripts/toolforge"
    shared = {"image": _IMAGE, "mount": "all", "no-filelog": True}
    return [
        {
            **shared,
            "name": "aranami-web",
            "command": f"exec sh {quote(str(scripts / 'run-web.sh'))}",
            "continuous": True,
            "port": 8000,
            "publish": "/",
            "mem": f"{WEB_MEMORY}Mi",
            "cpu": WEB_CPU / 1000,
        },
        *[
            {
                **shared,
                "name": job_name(name),
                "command": (
                    f"exec sh {quote(str(scripts / 'run-job.sh'))} {name}"
                ),
                "schedule": (
                    f"{allocation.minute} {JOB_DEFINITIONS[name].hour} * * *"
                ),
                "timeout": allocation.minutes * 60,
                "retry": 1,
                "mem": f"{allocation.memory}Mi",
                "cpu": allocation.cpu / 1000,
            }
            for name, allocation in ALLOCATIONS.items()
        ],
    ]


def configured_schedules(runtime: Path, now: dt.datetime) -> dict[str, dict]:
    """Expose planned launches when individual jobs are enabled.

    Args:
        runtime: Shared tool directory.
        now: Actual UTC observation time.

    Returns:
        Grouped report and collection plans, or an empty mapping in
        legacy scheduler mode.
    """
    if not (runtime / ACTIVE_PATH).is_file():
        return {}
    return {
        label: {
            name: {
                "state": "scheduled",
                "next_run_at": next_launch(name, now).isoformat(),
            }
            for name in definitions
        }
        for label, definitions in (
            ("routines", TASK_DEFINITIONS),
            ("collections", COLLECTION_DEFINITIONS),
        )
    }
