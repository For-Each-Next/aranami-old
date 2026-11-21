"""Keep current Toolforge job samples outside execution history."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from data.runtime.dataset_updates import planned_updates, read_updates
from data.runtime.resources import validate_usage
from data.runtime.status import read_status
from shared.support.files import atomic_json, read_json_object
from shared.toolforge.jobs import JOB_DEFINITIONS, ON_DEMAND, SERVICES
from shared.toolforge.state import STATE_DIRECTORY

if TYPE_CHECKING:
    from pathlib import Path

    from data.runtime.status import StatusReadCache

JOB_SAMPLES_DIRECTORY = STATE_DIRECTORY / "samples"
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
        runtime / JOB_SAMPLES_DIRECTORY / f"{task}.json",
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
                runtime / JOB_SAMPLES_DIRECTORY / f"{task}.json",
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


def read_live_status(
    runtime: Path,
    *,
    cache: StatusReadCache | None = None,
) -> dict:
    """Read status with job samples and dataset progress.

    Args:
        runtime: Runtime owner containing the independent observations.
        cache: Optional cache for the saved status generation.

    Returns:
        A read-only status view with validated runtime observations.
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
    return status
