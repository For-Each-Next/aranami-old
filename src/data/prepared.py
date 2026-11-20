"""Store bounded JSON objects with precomputed presentation values.

Readers accept retained one-cell Parquet files during the transition.
Owners validate domain facts and control how generations are selected.
"""

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import polars as pl

from data.paths import flat_path
from shared.support.cache import ParquetCache
from shared.support.files import atomic_json, read_json_object

MAX_BYTES = 16 * 1024 * 1024


def _read_legacy(path: Path, max_bytes: int) -> dict:
    """Decode the original one-cell Parquet contract.

    Returns:
        The complete object from a validated legacy file.

    Raises:
        ValueError: The legacy file has no complete object.
    """
    cache = ParquetCache(
        schema={"payload": pl.String},
        contract="prepared-values:1",
        max_rows=1,
        max_bytes=max_bytes,
    )
    frame = cache.read_required(path)
    if frame.height != 1 or frame["payload"].null_count():
        message = "Prepared data requires one complete payload."
        raise ValueError(message)
    value = json.loads(frame.item(0, "payload"))
    if not isinstance(value, dict):
        message = "Prepared data requires an object."
        raise ValueError(message)  # ruff: ignore[type-check-without-type-error]
    return value


def values_path(path: Path) -> Path:
    """Select the JSON path, with a fallback to retained Parquet.

    Returns:
        The physical path to read or inspect for cache invalidation.
    """
    if path.suffix not in {".json", ".parquet"}:
        return flat_path(path)
    current = flat_path(path.with_suffix(".json"))
    try:
        current.lstat()
    except FileNotFoundError:
        pass
    else:
        return current
    legacy = flat_path(path.with_suffix(".parquet"))
    try:
        legacy.lstat()
    except FileNotFoundError:
        return current
    return legacy


def read_values(path: Path, max_bytes: int = MAX_BYTES) -> dict:
    """Read the complete prepared object without calculating facts.

    Returns:
        The saved values, including null and empty values.
    """
    selected = values_path(path)
    if selected.suffix == ".parquet":
        return _read_legacy(selected, max_bytes)
    return read_json_object(selected, max_bytes)


def write_values(
    path: Path,
    value: dict,
    *,
    max_bytes: int = MAX_BYTES,
) -> None:
    """Atomically commit a bounded JSON object before readers run."""
    if path.suffix == ".parquet":
        path = path.with_suffix(".json")
    destination = flat_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(destination, value, max_bytes=max_bytes)
