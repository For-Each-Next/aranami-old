"""Read and write the shared UTC checkpoints for Toolforge workloads."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from shared.config import PAGEVIEWS_START_HOUR
from shared.support.files import atomic_json, read_json_object

STATE_DIRECTORY = Path("state/toolforge-jobs")
ACTIVE_PATH = STATE_DIRECTORY / "active"
GROUPED_PATH = STATE_DIRECTORY / "grouped"
SCHEDULES_PATH = STATE_DIRECTORY / "schedules.json"
_RECEIPT_BYTES = 512


def hour(instant: dt.datetime) -> dt.datetime:
    """Return the start of the selected UTC hour."""
    return instant.replace(minute=0, second=0, microsecond=0)


def midnight(instant: dt.datetime) -> dt.datetime:
    """Return the start of the selected UTC day."""
    return hour(instant).replace(hour=0)


def pageviews_cycle(instant: dt.datetime) -> dt.datetime:
    """Return the most recent daily Pageviews launch boundary.

    Returns:
        The UTC cycle shared by the initial launch and hourly retries.
    """
    current = hour(instant.astimezone(dt.UTC))
    start = current.replace(hour=PAGEVIEWS_START_HOUR)
    return start if current >= start else start - dt.timedelta(days=1)


def completed(
    runtime: Path,
    name: str,
    cycle: dt.datetime,
    *,
    through: dt.datetime | None = None,
) -> bool:
    """Check for a successful workload receipt.

    Args:
        runtime: Root containing the saved workload receipts.
        name: Workload receipt name.
        cycle: Expected checkpoint or earliest acceptable success.
        through: Allow a saved success through this UTC hour. Used by
            Pageviews to accept its previous per-hour receipts.

    Returns:
        Whether the workload completed this UTC cycle.
    """
    try:
        receipt = read_json_object(
            runtime / STATE_DIRECTORY / f"{name}.json",
            _RECEIPT_BYTES,
        )
    except OSError, ValueError:
        return False
    if through is None:
        return receipt == {"cycle": cycle.isoformat()}
    if set(receipt) != {"cycle"}:
        return False
    try:
        observed = dt.datetime.fromisoformat(receipt["cycle"])
    except TypeError, ValueError:
        return False
    return observed.utcoffset() is not None and cycle <= observed <= through


def record_completion(runtime: Path, name: str, cycle: dt.datetime) -> None:
    """Publish a workload checkpoint after its data commits."""
    atomic_json(
        runtime / STATE_DIRECTORY / f"{name}.json",
        {"cycle": cycle.isoformat()},
        max_bytes=_RECEIPT_BYTES,
    )


def fetch_outcome(runtime: Path, cycle: dt.datetime) -> str | None:
    """Read the fetch job's status for the requested hour.

    Returns:
        The last recorded outcome, or none if the hour is unknown.
    """
    try:
        value = read_json_object(
            runtime / STATE_DIRECTORY / "fetch-status.json",
            _RECEIPT_BYTES,
        )
    except OSError, ValueError:
        return None
    outcome = value.get("outcome")
    if value.get("cycle") == cycle.isoformat() and outcome in {
        "running",
        "succeeded",
        "failed",
    }:
        return outcome
    return None


def record_fetch(runtime: Path, cycle: dt.datetime, outcome: str) -> None:
    """Atomically report the phase that consumers wait for."""
    atomic_json(
        runtime / STATE_DIRECTORY / "fetch-status.json",
        {"cycle": cycle.isoformat(), "outcome": outcome},
        max_bytes=_RECEIPT_BYTES,
    )
