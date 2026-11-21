"""Migrate retained runtime tables in a temporary Toolforge job.

Run from the paused runtime directory with the selected source on
PYTHONPATH. The pause record keeps the verified plan, original tables,
and a completion receipt. Repeating apply continues the same plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

from data.articles import authorship_store
from data.articles.storage import AUTHORSHIP_PATH
from data.caching.project_observations import (
    link_daily_archive,
    resolve_daily_alias,
)
from data.reports import ReportStore
from shared.support.assessment_encoding import (
    TASKFORCE_FLAG_COLUMNS,
    TASKFORCE_LIST_COLUMNS,
    restore_assessment_schema,
)
from shared.support.files import atomic_json, read_json_object
from shared.support.parquet import validate_parquet_metadata
from shared.support.parquet_tables import (
    MAX_BYTES,
    is_nested,
    link_table,
    open_table,
    read_table,
    write_table,
)

_ROOTS = ("data", "cache", "reports", "dry-run")
_WORK = "scalar-parquet"
_FLAG_WORK = "taskforce-flags"
_OLD_TASKFORCE_COLUMNS = {
    column
    for name in TASKFORCE_LIST_COLUMNS
    for column in (name, name + "__length")
}
_ACTIVE = Path("state/toolforge-jobs/active")
_MAX_JSON = 8 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


def _files() -> list[Path]:
    """Enumerate regular retained files without following links.

    Returns:
        Runtime-relative paths for deterministic migration.
    """
    return sorted(
        Path(directory) / name
        for root in _ROOTS
        for directory, _dirs, names in os.walk(root)
        for name in names
        if not (Path(directory) / name).is_symlink()
    )


def _nested(path: Path) -> bool:
    """Check the physical schema without loading rows.

    Returns:
        Whether at least one physical column is nested.
    """
    return any(
        is_nested(dtype) for dtype in pl.read_parquet_schema(path).values()
    )


def _legacy_taskforces(path: Path) -> bool:
    """Identify an old task-force list or length marker.

    Returns:
        Whether the legacy membership still needs conversion.
    """
    return bool(_OLD_TASKFORCE_COLUMNS & pl.read_parquet_schema(path).keys())


def _has_flags(path: Path) -> bool:
    """Check the six physical membership fields.

    Returns:
        Whether all six Booleans have replaced the original list.
    """
    schema = pl.read_parquet_schema(path)
    return not (_OLD_TASKFORCE_COLUMNS & schema.keys()) and all(
        schema.get(name) == pl.Boolean for name in TASKFORCE_FLAG_COLUMNS
    )


def _digest(path: Path) -> str:
    """Hash bytes to identify immutable and staged tables.

    Returns:
        SHA-256 digest of the complete file.
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _backup(source: Path, originals: Path) -> None:
    """Retain the original inode before any replacement."""
    destination = originals / source
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == ".parquet":
        link_table(source, destination)
    else:
        os.link(source, destination)


def _json(path: Path) -> dict:
    """Read a report or migration manifest within the storage bound.

    Returns:
        The decoded manifest.
    """
    return read_json_object(path, _MAX_JSON)


def _load(path: Path, schema: dict | None = None) -> tuple[pl.DataFrame, dict]:
    """Read logical data with its recorded Enum declarations.

    Returns:
        Exact logical rows and their original owner metadata.
    """
    with open_table(path, MAX_BYTES) as stream:
        frame, metadata = read_table(path, stream)
    embedded = json.loads(metadata.get("aranami.storage", "{}"))
    owner = json.loads(metadata.get("aranami", "{}"))
    frame = restore_assessment_schema(
        frame,
        embedded.get("columns") or schema or owner.get("columns") or {},
    )
    validate_parquet_metadata(metadata, frame)
    # Polars regenerates the Arrow schema from the physical columns.
    metadata.pop("ARROW:schema", None)
    return frame, metadata


def _report_tables(files: list[Path]) -> dict[Path, tuple[Path, str, dict]]:
    """Locate table records in hierarchical and flattened manifests.

    Returns:
        Report manifest, table name, and file integrity metadata.
    """
    tables = {}
    for path in files:
        if not (
            path.name == "manifest.json"
            or path.name.endswith("--manifest.json")
        ):
            continue
        manifest = _json(path)
        if not isinstance(manifest.get("tables"), dict):
            continue
        prefix = path.name.removesuffix("manifest.json")
        for name, record in manifest["tables"].items():
            if (
                isinstance(record, dict)
                and (filename := record.get("file")) == f"{name}.parquet"
                and Path(filename).name == filename
                and isinstance(record.get("sha256"), str)
            ):
                artifact = path.with_name(prefix + filename)
                tables[artifact] = path, name, record
    return tables


def _stage_one(
    path: Path,
    staged: Path,
    originals: Path,
    schema: dict | None,
    *,
    flags: bool,
) -> dict[str, str]:
    """Save an original and verify logical equality before cutover.

    Returns:
        Digests of the original and converted file.

    Raises:
        ValueError: The conversion changed rows or their logical schema.
    """
    _backup(path, originals)
    source = originals / path
    frame, metadata = _load(source, schema)
    destination = staged / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    converted = write_table(destination, frame, metadata)
    destination.chmod(stat.S_IMODE(path.stat().st_mode))
    restored, _metadata = _load(destination, schema)
    if (
        (_nested(destination) or (flags and not _has_flags(destination)))
        or frame.schema != restored.schema
        or not frame.equals(restored)
    ):
        message = f"Scalar conversion changed rows or types for {path}"
        raise ValueError(message)
    return {"old": _digest(source), "new": converted}


def _daily_alias(path: Path) -> Path:
    """Resolve the project archive behind its hourly alias.

    Returns:
        The archive path or the standalone file path.
    """
    dry = path.parts[0] == "dry-run"
    relative = path.relative_to("dry-run") if dry else path
    root = Path("dry-run") if dry else Path()
    archive = resolve_daily_alias(relative.as_posix(), Path.cwd() / root)
    return root / archive


def _plan(work: Path, *, flags: bool) -> None:  # ruff: ignore[too-many-locals] - Keep staged operations together.
    """Stage verified conversions before changing live files.

    Raises:
        ValueError: A report declares a different original digest.
    """
    files = _files()
    reports = _report_tables(files)
    needs_conversion = _legacy_taskforces if flags else _nested
    candidates = {
        path
        for path in files
        if path.suffix == ".parquet" and needs_conversion(path)
    }
    with TemporaryDirectory(
        prefix=".scalar-plan-",
        dir=work.parent,
    ) as temporary:
        directory = Path(temporary) / work.name
        originals = directory / "originals"
        staged = directory / "prepared"
        standalone = {}
        bundles = {}
        aliases = {}
        for path in sorted(candidates):
            archive = _daily_alias(path)
            if archive != path and archive in candidates:
                aliases[str(path)] = {
                    "archive": str(archive),
                    "old": _digest(path),
                }
                continue
            if path == AUTHORSHIP_PATH:
                _backup(path, originals)
                continue
            report = reports.get(path)
            if report is None:
                standalone[str(path)] = _stage_one(
                    path,
                    staged,
                    originals,
                    None,
                    flags=flags,
                )
                continue
            manifest, name, entry = report
            records = bundles.setdefault(str(manifest), {})
            if not records:
                _backup(manifest, originals)
            change = _stage_one(
                path,
                staged,
                originals,
                entry.get("schema"),
                flags=flags,
            )
            if change["old"] != entry["sha256"]:
                message = f"Report manifest digest differs for {path}"
                raise ValueError(message)
            records[str(path)] = {**change, "name": name}
        directory.mkdir(parents=True, exist_ok=True)
        atomic_json(
            directory / "plan.json",
            {
                "standalone": standalone,
                "bundles": bundles,
                "aliases": aliases,
                "authorship": AUTHORSHIP_PATH in candidates,
            },
            max_bytes=_MAX_JSON,
        )
        directory.replace(work)
    _LOGGER.info(
        "Verified conversions for %s original tables.",
        len(candidates),
    )


def _install(path: Path, change: dict, work: Path) -> None:
    """Publish when the exact original or staged generation is selected.

    Raises:
        ValueError: Another writer changed the live file.
    """
    seen = _digest(path)
    if seen == change["old"]:
        link_table(work / "prepared" / path, path)
    elif seen != change["new"]:
        message = f"Live data changed during migration at {path}"
        raise ValueError(message)


def _install_alias(path: Path, change: dict) -> None:
    """Rejoin a daily alias to its new archive generation.

    Raises:
        ValueError: The live alias changed since preparing the plan.
    """
    archive = Path(change["archive"])
    if path.samefile(archive):
        return
    if _digest(path) != change["old"]:
        message = f"Live daily alias changed during migration at {path}"
        raise ValueError(message)
    link_daily_archive(
        archive,
        Path.cwd(),
        dry=path.parts[0] == "dry-run",
    )


def _commit_report(manifest: Path, changes: dict, work: Path) -> None:
    """Update physical digests while holding the report's lock.

    Raises:
        ValueError: The report has unrecognized table metadata.
    """
    original = work / "originals" / manifest
    key = _json(original)["report_key"]
    # Live readers share the runtime's report-lock namespace.
    runtime = Path.cwd()
    if manifest.parts[0] == "dry-run":
        runtime /= "dry-run"
    root = runtime / "data/parsed"
    with ReportStore(root).locked(key):
        current = _json(manifest)
        for filename, change in changes.items():
            table = current["tables"][change["name"]]
            if table["sha256"] not in {change["old"], change["new"]}:
                message = (
                    f"Report metadata changed during migration at {manifest}"
                )
                raise ValueError(message)
            _install(Path(filename), change, work)
            table["sha256"] = change["new"]
        atomic_json(manifest, current, max_bytes=_MAX_JSON)


def _verify(work: Path, plan: dict, *, flags: bool) -> None:  # ruff: ignore[complex-structure] - Verify each table owner.
    """Verify published digests and scan all runtime roots.

    Raises:
        ValueError: Stored evidence differs or nested columns remain.
    """
    for manifest, changes in plan["bundles"].items():
        current = _json(Path(manifest))
        for filename, change in changes.items():
            if current["tables"][change["name"]]["sha256"] != change["new"]:
                message = f"Unverified table manifest for {filename}"
                raise ValueError(message)
    selected = {
        **plan["standalone"],
        **{
            filename: change
            for changes in plan["bundles"].values()
            for filename, change in changes.items()
        },
    }
    for filename, change in selected.items():
        path = Path(filename)
        if _digest(path) != change["new"] or (flags and not _has_flags(path)):
            message = f"Unverified published table {path}"
            raise ValueError(message)
        _load(path)
    aliases = plan.get("aliases", {})
    for filename, change in aliases.items():
        path = Path(filename)
        if not path.samefile(change["archive"]):
            message = f"Unverified daily alias {path}"
            raise ValueError(message)
    if plan["authorship"]:
        original = authorship_store.load(work / "originals" / AUTHORSHIP_PATH)
        if AUTHORSHIP_PATH.exists() or not original.equals(
            authorship_store.load(AUTHORSHIP_PATH),
        ):
            message = "Unverified published listing and contributor tables."
            raise ValueError(message)
    files = [path for path in _files() if path.suffix == ".parquet"]
    needs_conversion = _legacy_taskforces if flags else _nested
    remaining = [str(path) for path in files if needs_conversion(path)]
    if remaining:
        message = f"Unconverted columns remain in {remaining}"
        raise ValueError(message)
    receipt = {
        "tables_scanned": len(files),
        "taskforce_list_tables" if flags else "nested_tables": 0,
        "converted_originals": len(selected) + int(plan["authorship"]),
        "relinked_aliases": len(aliases),
        "listing_authorship": plan["authorship"],
    }
    atomic_json(
        work.parent / f"{work.name}-verified.json",
        receipt,
        max_bytes=_MAX_JSON,
    )
    _LOGGER.info("Verified %s: %s", work.name, json.dumps(receipt))


def main() -> None:
    """Migrate retained Parquet while job admission is paused.

    Raises:
        ValueError: Active runtime or an invalid pause record.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pause_record", type=Path)
    parser.add_argument("--taskforce-flags", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    record = args.pause_record.resolve(strict=True)
    if (
        record.parent != Path.cwd() / "deployment-backups"
        or not (record / "cron-suspensions").is_file()
        or _ACTIVE.exists()
    ):
        message = "Expected the saved Toolforge pause record and paused jobs."
        raise ValueError(message)
    work = record / (_FLAG_WORK if args.taskforce_flags else _WORK)
    if not work.exists() and not args.verify:
        _plan(work, flags=args.taskforce_flags)
    if args.plan_only:
        return
    plan = _json(work / "plan.json")
    if not args.verify:
        for filename, change in plan["standalone"].items():
            _install(Path(filename), change, work)
        for manifest, changes in plan["bundles"].items():
            _commit_report(Path(manifest), changes, work)
        for filename, change in plan.get("aliases", {}).items():
            _install_alias(Path(filename), change)
        if (
            plan["authorship"]
            and AUTHORSHIP_PATH.exists()
            and authorship_store.normalize_storage(AUTHORSHIP_PATH)
        ):
            AUTHORSHIP_PATH.unlink()
    _verify(work, plan, flags=args.taskforce_flags)


if __name__ == "__main__":
    main()
