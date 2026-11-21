"""Read and write the shared UTC checkpoints for Toolforge workloads."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from shared.support.files import atomic_json, read_json_object

if TYPE_CHECKING:
    import datetime as dt

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


def completed(runtime: Path, name: str, cycle: dt.datetime) -> bool:
    """Check for a successful workload receipt.

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
    return receipt == {"cycle": cycle.isoformat()}


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
