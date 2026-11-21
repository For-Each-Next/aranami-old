"""Publish and read immutable, bounded Article List query tables."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from uuid import uuid4

import polars as pl

from shared.article_query import PROJECTS
from shared.support.cache import ParquetCache
from shared.support.files import atomic_json, read_json_object

if TYPE_CHECKING:
    from collections.abc import Iterable

DIRECTORY = "cache/article-query"
MAX_EDGE_ROWS = 1_600_000
MAX_TITLE_ROWS = 650_000
_GENERATION = re.compile(r"[0-9a-f]{32}")
_FORMAT = 1
_MANIFEST_BYTES = 4096
_EDGE = {"page_id": pl.Int64, "key": pl.String}
SCHEMAS = {
    "subjects": {
        "article_id": pl.Int64,
        "page_id": pl.Int64,
        "talk_id": pl.Int64,
        "title": pl.String,
        "known": pl.Boolean,
    },
    "assessment": {
        "page_id": pl.Int64,
        "project": pl.String,
        "grade": pl.String,
        "importance": pl.String,
    },
    "projects": {"project": pl.String},
    "cat": {**_EDGE, "depth": pl.UInt8},
    "tl": _EDGE,
    "link": _EDGE,
    "backlink": {**_EDGE, "via_redirect": pl.Boolean},
    "coverage": {"page_id": pl.Int64, "kind": pl.String, "depth": pl.UInt8},
    "titles": {"key": pl.String, "page_id": pl.Int64, "redirect": pl.String},
    "variants": {"key": pl.String, "target": pl.String},
}
_FILES = {
    f"{site}-{name}": schema
    for site in PROJECTS
    for name, schema in SCHEMAS.items()
}


def _table(name: str) -> ParquetCache:
    """Select the cache contract for a partition.

    Returns:
        A bounded reader and writer for the declared table schema.
    """
    return ParquetCache(
        schema=_FILES[name],
        contract=f"article-query:{_FORMAT}:{name}",
        reuse=True,
        max_bytes=128 * 1024 * 1024,
        max_rows=MAX_EDGE_ROWS,
        observe=False,
    )


def _manifest(path: Path) -> dict:
    """Read and validate a published generation manifest.

    Returns:
        A manifest whose generation names are safe to use as paths.

    Raises:
        ValueError: The manifest has an invalid schema or timestamp.
    """
    value = read_json_object(path, _MANIFEST_BYTES)
    generation = value.get("generation")
    previous = value.get("previous")
    observed = value.get("observed_at")
    invalid_generation = (
        value.get("schema") != _FORMAT
        or not isinstance(generation, str)
        or not _GENERATION.fullmatch(generation)
    )
    invalid_previous = previous is not None and (
        not isinstance(previous, str)
        or not _GENERATION.fullmatch(previous)
        or previous == generation
    )
    if (
        invalid_generation
        or invalid_previous
        or not isinstance(observed, str)
        or dt.datetime.fromisoformat(observed).utcoffset() != dt.timedelta(0)
    ):
        message = "Invalid Article List query generation."
        raise ValueError(message)
    return value


@dataclass(frozen=True, slots=True)
class QueryIndex:
    """Hold one selected generation for an entire evaluation."""

    directory: Path
    generation: str
    observed_at: str

    def read(self, site: str, name: str) -> pl.DataFrame:
        """Read one partition from this exact generation.

        Returns:
            The validated table for the requested site and relationship.
        """
        key = f"{site}-{name}"
        return _table(key).read_required(self.directory / f"{key}.parquet")


def load(runtime: Path, generation: str | None = None) -> QueryIndex | None:
    """Select the latest saved query index or its retained predecessor.

    Returns:
        A complete selected generation, or none before collection.

    Raises:
        LookupError: The requested generation has expired.
    """
    root = runtime / DIRECTORY
    try:
        selected = _manifest(root / "current.json")
    except FileNotFoundError:
        if generation is None:
            return None
        raise LookupError(generation) from None
    current = selected["generation"]
    if generation is None or generation == current:
        return QueryIndex(root / current, current, selected["observed_at"])
    if generation != selected.get("previous"):
        raise LookupError(generation)
    previous = _manifest(root / generation / "manifest.json")
    if previous["generation"] != generation:
        raise LookupError(generation)
    return QueryIndex(root / generation, generation, previous["observed_at"])


def publish(
    runtime: Path,
    observed_at: dt.datetime,
    partitions: Iterable[tuple[str, str, pl.DataFrame]],
) -> None:
    """Stage, validate and atomically publish one complete query index.

    The caller holds the collector lease. A failed stage leaves the
    current generation available for existing pagination.

    Raises:
        OSError: The index directory is unsafe or could not be written.
        ValueError: A required partition is missing or repeated.
    """
    root = runtime / DIRECTORY
    if root.is_symlink() or root.parent.is_symlink():
        message = "The query cache requires regular directories."
        raise OSError(message)
    root.mkdir(parents=True, exist_ok=True)
    for abandoned in root.glob("stage-*"):
        if abandoned.is_dir() and not abandoned.is_symlink():
            rmtree(abandoned, ignore_errors=True)
    current = load(runtime)
    if current is not None and observed_at <= dt.datetime.fromisoformat(
        current.observed_at,
    ):
        return
    generation = uuid4().hex
    manifest = {
        "schema": _FORMAT,
        "generation": generation,
        "previous": current.generation if current is not None else None,
        "observed_at": observed_at.astimezone(dt.UTC).isoformat(),
    }
    with TemporaryDirectory(prefix="stage-", dir=root) as temporary:
        stage = Path(temporary) / generation
        stage.mkdir()
        written = set()
        for site, name, frame in partitions:
            key = f"{site}-{name}"
            if key in written:
                message = "Duplicate Article List query partition."
                raise ValueError(message)
            _table(key).write(stage / f"{key}.parquet", frame)
            written.add(key)
        if written != _FILES.keys():
            message = "Incomplete Article List query index."
            raise ValueError(message)
        atomic_json(
            stage / "manifest.json",
            manifest,
            max_bytes=_MANIFEST_BYTES,
        )
        stage.rename(root / generation)
        atomic_json(root / "current.json", manifest, max_bytes=_MANIFEST_BYTES)
    for path in root.iterdir():
        if (
            _GENERATION.fullmatch(path.name)
            and path.name not in {generation, manifest["previous"]}
            and path.is_dir()
            and not path.is_symlink()
        ):
            rmtree(path, ignore_errors=True)
