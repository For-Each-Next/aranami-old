"""Retain container resource observations outside status history.

The hub writes one bounded sample per second. Read-only web consumers
combine only fresh samples from the selected scheduler's exact boot.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import TYPE_CHECKING

from data.runtime.dataset_updates import planned_updates, read_updates
from data.runtime.resources import validate_runtime, validate_usage
from data.runtime.status import read_status
from shared.support.files import atomic_json, read_json_object
from shared.toolforge.jobs import JOB_DEFINITIONS, ON_DEMAND, SERVICES
from shared.toolforge.state import STATE_DIRECTORY

if TYPE_CHECKING:
    from data.runtime.status import StatusReadCache

SAMPLE_PATH = Path("state/observability/server-sample.json")
_MAX_BYTES = 16 * 1024
_MAX_AGE = dt.timedelta(seconds=120)
_JOB_SAMPLE_PATH = STATE_DIRECTORY / "samples"
_JOB_SAMPLE_BYTES = 2048
_JOB_SAMPLE_AGE = dt.timedelta(seconds=35)
_JOB_OUTCOMES = {"running", "succeeded", "failed"}


def save_job_sample(
    runtime: Path,
    task: str,
    started: dt.datetime,
    outcome: str,
    resources: dict,
) -> None:
    """Record one owned invocation without touching other jobs' state.

    Args:
        runtime: Shared Toolforge runtime directory.
        task: Configured job task.
        started: Actual start of this job invocation in UTC.
        outcome: Current launcher lifecycle.
        resources: Container readings, including unknown values.

    Raises:
        ValueError: The job, clock, state or resources are invalid.
    """
    if (
        task not in JOB_DEFINITIONS | SERVICES | ON_DEMAND
        or outcome not in _JOB_OUTCOMES
        or started.utcoffset() != dt.timedelta(0)
    ):
        message = "Invalid Toolforge sample identity."
        raise ValueError(message)
    atomic_json(
        runtime / _JOB_SAMPLE_PATH / f"{task}.json",
        {
            "schema": 1,
            "started_at": started.isoformat(),
            "observed_at": dt.datetime.now(dt.UTC).isoformat(),
            "outcome": outcome,
            "resources": validate_usage(resources),
        },
        max_bytes=_JOB_SAMPLE_BYTES,
    )


def _job_samples(runtime: Path, status: dict) -> dict[str, dict]:
    """Read the latest launcher observation for each installed job.

    Returns:
        Validated samples, with current resource freshness marked.
    """
    schedules = status["toolforge_schedules"]
    now = dt.datetime.fromisoformat(status["as_of"])
    activated = dt.datetime.fromisoformat(schedules["active_since"])
    samples = {}
    jobs = (
        schedules["services"].keys() | ON_DEMAND.keys()
        if "services" in schedules
        else schedules["collections"].keys() | schedules["routines"].keys()
    )
    for task in jobs:
        try:
            sample = read_json_object(
                runtime / _JOB_SAMPLE_PATH / f"{task}.json",
                _JOB_SAMPLE_BYTES,
            )
            started = dt.datetime.fromisoformat(sample["started_at"])
            observed = dt.datetime.fromisoformat(sample["observed_at"])
            resources = validate_usage(sample["resources"])
        except OSError, ValueError, TypeError, KeyError:
            continue
        outcome = sample.get("outcome")
        if (
            sample.get("schema") != 1
            or not isinstance(outcome, str)
            or outcome not in _JOB_OUTCOMES
            or started.utcoffset() != dt.timedelta(0)
            or observed.utcoffset() != dt.timedelta(0)
        ):
            continue
        if not activated <= started <= observed <= now:
            continue
        if task in ON_DEMAND and now - observed >= dt.timedelta(days=1):
            continue
        samples[task] = {
            "started_at": sample["started_at"],
            "observed_at": sample["observed_at"],
            "outcome": outcome,
            "resources": resources,
            "expires_at": (observed + _JOB_SAMPLE_AGE).isoformat()
            if now - observed < _JOB_SAMPLE_AGE
            else None,
        }
    return samples


def save_sample(
    resources: dict,
    *,
    boot_id: str,
    observed_at: dt.datetime,
    runtime: Path = Path(),
    dry: bool = False,
) -> None:
    """Atomically retain one bounded hub resource observation.

    Args:
        resources: Explicit local measurements from the hub sampler.
        boot_id: Exact owning scheduler process identity.
        observed_at: Actual aware UTC sampling time.
        runtime: Runtime root independent of the source generation.
        dry: Write only to the isolated preview tree.

    Raises:
        ValueError: Identity, clock or resource values are invalid.
    """
    if re.fullmatch(
        r"[0-9a-f]{32}",
        boot_id,
    ) is None or observed_at.utcoffset() != dt.timedelta(0):
        message = "Server samples require a boot identity and UTC clock."
        raise ValueError(message)
    path = runtime / (Path("dry-run") / SAMPLE_PATH if dry else SAMPLE_PATH)
    atomic_json(
        path,
        {
            "schema": 1,
            "boot_id": boot_id,
            "observed_at": observed_at.isoformat(),
            "resources": validate_runtime(resources),
        },
        max_bytes=_MAX_BYTES,
    )


def read_live_status(
    runtime: Path,
    *,
    cache: StatusReadCache | None = None,
) -> dict:
    """Combine saved status with a fresh sample from the same hub boot.

    Args:
        runtime: Runtime owner containing the independent observations.
        cache: Optional cache for the saved hub generation.

    Returns:
        A read-only derived status view. Missing, stale, malformed or
        different-boot samples leave the original saved status intact.
    """
    updates = read_updates(runtime.absolute())
    status = read_status(runtime, cache=cache)
    status["dataset_updates"] = updates
    status["dataset_updates"]["planned"] = planned_updates(
        runtime.absolute(),
        status,
    )
    if status.get("toolforge_schedules"):
        status["toolforge_samples"] = _job_samples(runtime, status)
    service = status.get("services", {}).get("scheduler")
    if service is None or service.get("lifecycle") != "running":
        return status
    try:  # ruff: ignore[too-many-statements-in-try-clause] - Optional sample validation falls back atomically.
        sample = read_json_object(runtime / SAMPLE_PATH, _MAX_BYTES)
        if (
            set(sample) != {"schema", "boot_id", "observed_at", "resources"}
            or sample["schema"] != 1
            or sample["boot_id"] != service.get("boot_id")
        ):
            return status
        observed = dt.datetime.fromisoformat(sample["observed_at"])
        now = dt.datetime.fromisoformat(status["as_of"])
        heartbeat = dt.datetime.fromisoformat(service["heartbeat_at"])
        if (
            observed.utcoffset() != dt.timedelta(0)
            or not dt.timedelta(0) <= now - observed <= _MAX_AGE
            or observed < heartbeat
        ):
            return status
        resources = validate_runtime(sample["resources"])
    except OSError, ValueError, KeyError, TypeError:
        return status
    return {
        **status,
        "services": {
            **status["services"],
            "scheduler": {
                **service,
                "resources": resources,
                "heartbeat_at": sample["observed_at"],
                "freshness": "current"
                if now - observed <= dt.timedelta(seconds=90)
                else "stale",
            },
        },
    }
