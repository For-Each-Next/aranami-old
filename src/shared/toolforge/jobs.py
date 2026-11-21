"""Define Toolforge services and expose their installed schedules."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from shlex import quote
from typing import TYPE_CHECKING

from shared.config import COLLECTION_DEFINITIONS, TASK_DEFINITIONS
from shared.support.files import atomic_json, read_json_object
from shared.toolforge.state import (
    ACTIVE_PATH,
    GROUPED_PATH,
    SCHEDULES_PATH,
    completed,
    hour,
)

if TYPE_CHECKING:
    from pathlib import Path

JOB_DEFINITIONS = COLLECTION_DEFINITIONS | TASK_DEFINITIONS
PROJECT_SNAPSHOT = "project-data"
PROJECT_HOURLY = "project-hourly"
DATA_FETCH = "data-fetch"
REPORT_UPDATE = "report-update"
ARTICLE_STATISTICS = "article-statistics"
MAINTENANCE = "data-maintenance"
WEBSITE_FETCH = "website-fetch"
FETCH_WORKLOADS = ("newsletter-history", WEBSITE_FETCH)
REPORT_WORKLOADS = (
    "dyks",
    "newsletter-daily",
    "website",
    "assessment_log",
    "assessment_lists",
    "enwp_key_articles",
    "new_pages",
    "pageviews",
    "pexbot",
)
ARTICLE_WORKLOADS = ("quality-analysis", "quality-authorship")
WORKLOAD_SERVICES = {
    PROJECT_SNAPSHOT: PROJECT_SNAPSHOT,
    PROJECT_HOURLY: DATA_FETCH,
    **dict.fromkeys(FETCH_WORKLOADS, DATA_FETCH),
    **dict.fromkeys(ARTICLE_WORKLOADS, DATA_FETCH),
    **dict.fromkeys(
        (f"fetch-{name}" for name in (*TASK_DEFINITIONS, "newsletter-daily")),
        DATA_FETCH,
    ),
    **dict.fromkeys(
        (*REPORT_WORKLOADS, "article-statistics-output"),
        REPORT_UPDATE,
    ),
}
_IMAGE = "python3.13"
_SCHEDULE_BYTES = 16 * 1024
_MAX_CRON_LENGTH = 120
_MAX_ZONE_LENGTH = 80
_KIB = 1024
_MEMORY_UNITS = {"": 1, "Ki": _KIB, "Mi": _KIB**2, "Gi": _KIB**3}
_MEMORY_LIMIT = re.compile(r"([0-9]{1,12})(Ki|Mi|Gi)?")
_CPU_LIMIT = re.compile(r"([0-9]{1,9}(?:\.[0-9]{1,9})?)(m)?")
_UTC_CRON = re.compile(
    r"([0-9]|[0-5][0-9]) (\*|[01]?[0-9]|2[0-3]) \* \* (\*|[0-6])",
)


@dataclass(frozen=True, slots=True)
class JobAllocation:
    """Describe the scheduled launch and resource limits of one worker.

    Attributes:
        minute: UTC launch minute after the nominal source boundary.
        minutes: Maximum wall time, including waits and retries.
        memory: Container memory limit in MiB.
        cpu: Container CPU limit in millicores.
        hour: Cron hour, or a wildcard for hourly runs.
    """

    minute: int
    minutes: int
    memory: int
    cpu: int
    hour: str = "*"


WEB_MEMORY = 2048
WEB_CPU = 1000
SERVICES = {
    PROJECT_SNAPSHOT: JobAllocation(0, 8, 1280, 500, hour="0"),
    DATA_FETCH: JobAllocation(2, 33, 1280, 1000),
    REPORT_UPDATE: JobAllocation(10, 48, 1536, 1000),
}
ON_DEMAND = {
    ARTICLE_STATISTICS: {"mem": "1536Mi", "cpu": 0.75, "retry": 2},
    MAINTENANCE: {"mem": "512Mi", "cpu": 0.25, "retry": 0},
}
MAINTENANCE_CRON = "40 3 * * 0"


def _next_launch(cron: str, now: dt.datetime) -> dt.datetime | None:
    """Calculate Aranami's next hourly or daily UTC launch.

    Returns:
        A UTC boundary, or none for other cron forms.
    """
    match = _UTC_CRON.fullmatch(cron)
    if match is None:
        return None
    minute, hour_field, weekday = match.groups()
    launch = now.replace(minute=int(minute), second=0, microsecond=0)
    if hour_field == "*":
        return launch if launch > now else launch + dt.timedelta(hours=1)
    launch = launch.replace(hour=int(hour_field))
    if weekday != "*":
        days = (int(weekday) - (now.weekday() + 1) % 7) % 7
        return launch + dt.timedelta(days=days or (7 if launch <= now else 0))
    return launch if launch > now else launch + dt.timedelta(days=1)


def job_name(name: str) -> str:
    """Return the Toolforge name for a configured workload.

    Args:
        name: Report or collection identifier.

    Returns:
        A DNS-compatible job name with the tool prefix.
    """
    return f"aranami-{name.replace('_', '-')}"


def job_definitions(
    runtime: Path,
    *,
    on_demand: bool = False,
    weekly_maintenance: bool = False,
) -> list[dict[str, object]]:
    """Generate a Jobs Framework configuration for this tool.

    Args:
        runtime: Shared tool directory containing the selected source.
        on_demand: Include one-off jobs for selective loading.
        weekly_maintenance: Schedule the completeness check on Sundays.

    Returns:
        Public web and separately scheduled background job definitions.
    """
    scripts = runtime / "app/scripts/toolforge"
    shared = {"image": _IMAGE, "mount": "all", "no-filelog": True}

    def launcher(name: str) -> dict[str, object]:
        """Use the pinned entry point for a background job.

        Returns:
            Shared job parameters and its command.
        """
        return {
            **shared,
            "name": job_name(name),
            "command": f"exec sh {quote(str(scripts / 'run-job.sh'))} {name}",
        }

    definitions = [
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
                **launcher(name),
                "schedule": f"{allocation.minute} {allocation.hour} * * *",
                "timeout": allocation.minutes * 60,
                "retry": 1,
                "mem": f"{allocation.memory}Mi",
                "cpu": allocation.cpu / 1000,
            }
            for name, allocation in SERVICES.items()
        ],
    ]
    if on_demand:
        definitions.extend(
            {**launcher(name), **limits}
            for name, limits in ON_DEMAND.items()
            if name != MAINTENANCE or not weekly_maintenance
        )
    if weekly_maintenance:
        definitions.append({
            **launcher(MAINTENANCE),
            **ON_DEMAND[MAINTENANCE],
            "schedule": MAINTENANCE_CRON,
            "timeout": 5 * 60,
        })
    return definitions


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
    known = {job_name(name) for name in JOB_DEFINITIONS | SERVICES | ON_DEMAND}
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

    grouped = (runtime / GROUPED_PATH).is_file()

    def schedules(
        definitions: dict,
        *,
        workloads: bool = False,
    ) -> dict[str, dict]:
        """Build launch times for known installed jobs.

        Returns:
            Valid installed definitions keyed by application task ID.
        """
        result = {}
        for name, definition in definitions.items():
            owner = WORKLOAD_SERVICES[name] if grouped and workloads else name
            identifier = job_name(owner)
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
            if (
                grouped
                and workloads
                and launch is not None
                and definition.hour == "0"
                and completed(runtime, name, hour(now).replace(hour=0))
            ):
                launch = hour(now).replace(
                    hour=0,
                    minute=launch.minute,
                ) + dt.timedelta(days=1)
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

    collections = schedules(COLLECTION_DEFINITIONS, workloads=True)
    if grouped:
        services = schedules(SERVICES | {MAINTENANCE: None})
        if DATA_FETCH in services:
            collections[WEBSITE_FETCH] = services[DATA_FETCH]
            collections[PROJECT_HOURLY] = services[DATA_FETCH]
    else:
        services = {}
    return {
        "active_since": active_since.isoformat(),
        "collections": collections,
        "routines": schedules(TASK_DEFINITIONS, workloads=True),
        **({"services": services} if grouped else {}),
    }
