"""Define Aranami's Toolforge jobs and initial allocations."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from shlex import quote

from shared.config import COLLECTION_DEFINITIONS, TASK_DEFINITIONS
from shared.support.files import atomic_json, read_json_object

STATE_DIRECTORY = Path("state/toolforge-jobs")
ACTIVE_PATH = STATE_DIRECTORY / "active"
SCHEDULES_PATH = STATE_DIRECTORY / "schedules.json"
JOB_DEFINITIONS = COLLECTION_DEFINITIONS | TASK_DEFINITIONS
_IMAGE = "python3.13"
_SCHEDULE_BYTES = 16 * 1024
_MAX_CRON_LENGTH = 120
_MAX_ZONE_LENGTH = 80
_KIB = 1024
_MEMORY_UNITS = {"": 1, "Ki": _KIB, "Mi": _KIB**2, "Gi": _KIB**3}
_MEMORY_LIMIT = re.compile(r"([0-9]{1,12})(Ki|Mi|Gi)?")
_CPU_LIMIT = re.compile(r"([0-9]{1,9}(?:\.[0-9]{1,9})?)(m)?")
_UTC_CRON = re.compile(r"([0-9]|[0-5][0-9]) (\*|[01]?[0-9]|2[0-3]) \* \* \*")


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
    "newsletter-history": JobAllocation(2, 10, 1024, 750),
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
    "quality-authorship": JobAllocation(47, 11, 1536, 750),
}
WEB_MEMORY = 2048
WEB_CPU = 1000


def _next_launch(cron: str, now: dt.datetime) -> dt.datetime | None:
    """Calculate Aranami's next hourly or daily UTC launch.

    Returns:
        A UTC boundary, or none for other cron forms.
    """
    match = _UTC_CRON.fullmatch(cron)
    if match is None:
        return None
    minute, hour = match.groups()
    launch = now.replace(minute=int(minute), second=0, microsecond=0)
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


def _container_limits(spec: dict) -> dict[str, int | float | None]:
    """Read the ordinary Toolforge quantities from the job container.

    Returns:
        Observed limits in bytes and CPU cores.
    """
    template = spec.get("jobTemplate", {}).get("spec", {}).get("template", {})
    resources = next(
        (
            container.get("resources", {}).get("limits", {})
            for container in template.get("spec", {}).get("containers", [])
            if container.get("name") == "job"
        ),
        {},
    )
    memory = _MEMORY_LIMIT.fullmatch(str(resources.get("memory", "")))
    cpu = _CPU_LIMIT.fullmatch(str(resources.get("cpu", "")))
    return {
        "memory_limit_bytes": int(memory[1]) * _MEMORY_UNITS[memory[2] or ""]
        if memory
        else None,
        "cpu_limit": float(cpu[1]) / (1000 if cpu[2] else 1) if cpu else None,
    }


def save_installed_schedules(runtime: Path, cronjobs: dict) -> None:
    """Save public schedule fields from the tool's installed CronJobs.

    Args:
        runtime: Shared tool directory.
        cronjobs: Kubernetes list obtained by the tool maintainer.

    Raises:
        TypeError: The input is not a Kubernetes list.
        ValueError: An installed job has invalid or duplicate metadata.
    """
    if not isinstance(cronjobs, dict) or not isinstance(
        cronjobs.get("items"),
        list,
    ):
        message = "Expected a Kubernetes CronJob list."
        raise TypeError(message)
    known = {job_name(name) for name in JOB_DEFINITIONS}
    jobs = {}
    for item in cronjobs["items"]:
        name = item["metadata"]["name"]
        if name not in known:
            continue
        spec = item["spec"]
        cron = spec["schedule"]
        zone = spec.get("timeZone") or "Etc/UTC"
        suspended = spec.get("suspend", False)
        if name in jobs:
            message = "Duplicate installed Toolforge schedule."
            raise ValueError(message)
        if (
            not isinstance(cron, str)
            or not isinstance(zone, str)
            or not isinstance(suspended, bool)
            or not 0 < len(cron) <= _MAX_CRON_LENGTH
            or not 0 < len(zone) <= _MAX_ZONE_LENGTH
        ):
            message = "Invalid installed Toolforge schedule."
            raise ValueError(message)
        jobs[name] = {
            "cron": " ".join(cron.split()),
            "zone": zone,
            "suspended": suspended,
            **_container_limits(spec),
        }
    atomic_json(
        runtime / SCHEDULES_PATH,
        {"schema": 1, "jobs": jobs},
        max_bytes=_SCHEDULE_BYTES,
    )


def installed_schedules(runtime: Path, now: dt.datetime) -> dict[str, object]:
    """Read the last observed Toolforge schedule from shared storage.

    Returns:
        Enabled time and job plans, or an empty mapping in legacy mode.
    """
    try:
        active_since = dt.datetime.fromtimestamp(
            (runtime / ACTIVE_PATH).stat().st_mtime,
            dt.UTC,
        )
    except FileNotFoundError:
        return {}
    try:
        saved = read_json_object(runtime / SCHEDULES_PATH, _SCHEDULE_BYTES)
        jobs = saved["jobs"]
        if saved["schema"] != 1 or not isinstance(jobs, dict):
            jobs = {}
    except OSError, ValueError, KeyError:
        jobs = {}

    def schedules(definitions: dict) -> dict[str, dict]:
        """Build launch times for known installed jobs.

        Returns:
            Valid installed definitions keyed by application task ID.
        """
        result = {}
        for name in definitions:
            identifier = job_name(name)
            job = jobs.get(identifier)
            if (
                not isinstance(job, dict)
                or not isinstance(job.get("cron"), str)
                or not isinstance(job.get("zone"), str)
                or not isinstance(job.get("suspended"), bool)
            ):
                continue
            cron = job["cron"]
            suspended = job["suspended"]
            launch = (
                _next_launch(cron, now)
                if not suspended and job["zone"] in {"UTC", "Etc/UTC"}
                else None
            )
            result[name] = {
                "job_name": identifier,
                "state": "paused" if suspended else "scheduled",
                "next_run_at": launch.isoformat() if launch else None,
                "cron": cron,
                "zone": job["zone"],
                "memory_limit_bytes": job.get("memory_limit_bytes")
                if type(job.get("memory_limit_bytes")) is int
                else None,
                "cpu_limit": job.get("cpu_limit")
                if type(job.get("cpu_limit")) in {int, float}
                else None,
            }
        return result

    return {
        "active_since": active_since.isoformat(),
        "collections": schedules(COLLECTION_DEFINITIONS),
        "routines": schedules(TASK_DEFINITIONS),
    }
