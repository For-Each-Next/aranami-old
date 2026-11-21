"""Write scalar Parquet tables and reconstruct their keyed relations.

Each parent binds immutable children by name and digest. Publishing the
parent selects the whole set. Keys are row identifiers within a table,
and positions preserve repetitions, order, and null elements.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
from contextlib import contextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from uuid import uuid4

import polars as pl

from shared.support.assessment_encoding import (
    encode_taskforce_flags,
    restore_assessment_schema,
    restore_taskforce_flags,
)
from shared.support.files import open_regular, staging_directory
from shared.support.parquet import parquet_metadata, validate_parquet_metadata

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from typing import BinaryIO

RELATIONS = "aranami.relations"
TASKFORCE_FLAGS = "aranami.taskforce_flags"
_STORAGE = "aranami.storage"
_DIRECTORY = "parquet-children"
_ROW = "__row_id"
_PARENT = "__parent_row_id"
_POSITION = "__position"
_POSITIONS = "__child_positions"
_VALUE = "__value"
_PRESENT = "__value_present"
_TOKEN = re.compile(r"[0-9a-f]{32}")
_CHILD = re.compile(r"[a-z0-9_-]{1,100}\.parquet")
_MAX_META = 1024 * 1024
_MAX_ROWS = 20_000_000
MAX_BYTES = 512 * 1024 * 1024
_MAX_DEPTH = 8
_INVALID = "Invalid Parquet child table or relationship."
_JOB_FAMILIES = {
    "assessment-comparison-": "assessment-comparison",
    "assessment-log-": "assessment-log",
    "dyk-": "dyks",
    "newsletter--": "newsletter",
    "pageviews-": "aranami-pageviews",
}


def is_nested(dtype: pl.DataType) -> bool:
    """Classify a physical Parquet data type.

    Returns:
        Whether its values need a keyed child table.
    """
    return isinstance(dtype, (pl.List, pl.Array, pl.Struct))


def _sync(path: Path) -> None:
    """Flush directory entries before making a parent visible."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _root(path: Path) -> Path:
    """Locate the children beside their parent file.

    Returns:
        The namespace's shared directory for immutable child files.

    Raises:
        OSError: The child namespace is a symbolic link.
    """
    owner = path.parent
    data = owner.parent
    root = owner / _DIRECTORY
    if owner.name in {"archive", "raw", "parsed"} and data.name == "data":
        job = next(
            (
                job
                for prefix, job in _JOB_FAMILIES.items()
                if path.name.startswith(prefix)
            ),
            None,
        )
        group = data / "jobs" / job if job else data / "shared"
        root = group / f"{owner.name}-children"
    if any(
        directory.is_symlink()
        for directory in (root, *root.parents)
        if directory.is_relative_to(data) and directory != data
    ):
        message = "Parquet child directories must be regular directories."
        raise OSError(message)
    return root


def _generation(path: Path, identifier: str) -> Path:
    """Keep independently prunable child sets for each parent name.

    Returns:
        Directory containing immutable child files.
    """
    name = hashlib.sha256(path.name.encode()).hexdigest()[:24]
    return _root(path) / (name + "-" + identifier)


def _lease(
    root: Path,
    *,
    writing: bool = False,
    create: bool = False,
) -> int | None:
    """Open the directory-wide replacement lock.

    Returns:
        Its file descriptor, or none before the first replacement.

    Raises:
        FileNotFoundError: A requested lock could not be created.
    """
    if create:
        root.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(
            root / ".lock",
            (os.O_RDWR if writing else os.O_RDONLY)
            | (os.O_CREAT if create else 0)
            | os.O_NOFOLLOW
            | os.O_NONBLOCK,
            0o600,
        )
    except FileNotFoundError:
        if create:
            raise
        return None


@contextmanager
def open_table(path: Path, max_bytes: int) -> Iterator[BinaryIO]:
    """Pin the parent and its immutable children during reads.

    Yields:
        A bounded regular Parquet stream under the read lease.
    """
    with open_regular(path, max_bytes) as initial:
        descriptor = _lease(_root(path))
        if descriptor is None:
            # No writer had published a mutable generation at open time.
            yield initial
            return
        with os.fdopen(descriptor, "rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            with open_regular(path, max_bytes) as current:
                yield current


def _metadata(stream: BinaryIO) -> dict[str, str]:
    """Read the footer and rewind the same open file.

    Returns:
        Metadata from the captured file.
    """
    metadata = pl.read_parquet_metadata(stream)
    stream.seek(0)
    return metadata


def _layout(metadata: Mapping[str, str]) -> dict | None:
    """Decode the parent relationship descriptor.

    Returns:
        The stored layout, or none for a standalone Parquet table.

    Raises:
        ValueError: Layout metadata is oversized or invalid.
    """
    value = metadata.get(RELATIONS)
    if value is None:
        return None
    if len(value.encode()) > _MAX_META:
        raise ValueError(_INVALID)
    layout = json.loads(value)
    if (
        not isinstance(layout, dict)
        or layout.get("schema") != 1
        or not isinstance(layout.get("id"), str)
        or _TOKEN.fullmatch(layout["id"]) is None
    ):
        raise ValueError(_INVALID)
    return layout


def _children(path: Path) -> Path | None:
    """Locate the child generation of an existing physical parent.

    Returns:
        Its directory, or none for an absent or standalone file.
    """
    try:
        with open_regular(path, MAX_BYTES) as stream:
            layout = _layout(_metadata(stream))
    except FileNotFoundError:
        return None
    return _generation(path, layout["id"]) if layout is not None else None


def _write(path: Path, frame: pl.DataFrame, metadata: dict[str, str]) -> str:
    """Write and sync a physical table.

    Returns:
        The digest of the complete file.
    """
    frame.write_parquet(path, metadata=metadata)
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _split_column(
    frame: pl.DataFrame,
    name: str,
    dtype: pl.DataType,
) -> tuple[pl.Expr, pl.DataFrame, dict]:
    """Build one relationship with an explicit parent key.

    Returns:
        Parent marker, ordered child rows, and logical type metadata.
    """
    parent = pl.col(_ROW).alias(_PARENT)
    value = pl.col(name)
    if isinstance(dtype, pl.Struct):
        fields = [field.name for field in dtype.fields]
        child = frame.filter(value.is_not_null()).select(
            parent,
            *(value.struct.field(field) for field in fields),
        )
        return value.is_not_null(), child, {"kind": "struct", "fields": fields}

    values = value.arr.to_list() if isinstance(dtype, pl.Array) else value
    length = values.list.len()
    child = (
        frame
        .filter(length > 0)
        .select(
            parent,
            values.alias(_VALUE),
            pl.int_ranges(0, length, dtype=pl.UInt32).alias(_POSITION),
        )
        .explode(_VALUE, _POSITION)
    )
    fields = None
    if isinstance(child.schema[_VALUE], pl.Struct):
        fields = [field.name for field in child.schema[_VALUE].fields]
        child = child.select(
            _PARENT,
            _POSITION,
            pl.col(_VALUE).is_not_null().alias(_PRESENT),
            *(pl.col(_VALUE).struct.field(field) for field in fields),
        )
    return (
        length,
        child,
        {
            "kind": "list",
            "fields": fields,
            "width": dtype.size if isinstance(dtype, pl.Array) else None,
        },
    )


def _split(
    frame: pl.DataFrame,
    directory: Path,
    prefix: str,
    depth: int = 0,
) -> tuple[pl.DataFrame, dict]:
    """Stage child tables in the order of their logical columns.

    Returns:
        Scalar parent rows and the complete relationship descriptor.

    Raises:
        ValueError: The table exceeds the supported layout.
    """
    nested = [
        (name, dtype)
        for name, dtype in frame.schema.items()
        if is_nested(dtype)
    ]
    if not nested:
        return frame, {}
    if _ROW in frame.columns or depth >= _MAX_DEPTH:
        raise ValueError(_INVALID)
    indexed = frame.with_row_index(_ROW)
    relations = {}
    markers = []
    for number, (name, dtype) in enumerate(nested):
        marker, child, relation = _split_column(indexed, name, dtype)
        marker_name = name + (
            "__present" if relation["kind"] == "struct" else "__length"
        )
        if marker_name in frame.columns:
            raise ValueError(_INVALID)
        slug = re.sub(r"[^a-z0-9_]+", "-", name.lower()).strip("-")[:28]
        identifier = f"{prefix}{number}-"
        filename = identifier + (slug or "values") + ".parquet"
        physical, layout = _split(child, directory, identifier, depth + 1)
        digest = _write(
            directory / filename,
            physical,
            parquet_metadata(physical, contract="parquet-child"),
        )
        markers.append(marker.alias(marker_name))
        relations[name] = {
            **relation,
            "marker": marker_name,
            "file": filename,
            "sha256": digest,
            "layout": layout,
        }
    parent = indexed.with_columns(markers).drop(*relations)
    return parent, {"columns": frame.columns, "relations": relations}


def _column_metadata(metadata: str, frame: pl.DataFrame) -> str:
    """Update the schema in an existing storage envelope.

    Returns:
        Storage metadata for the physical columns.
    """
    envelope = json.loads(metadata)
    envelope["columns"] = {
        name: str(dtype) for name, dtype in frame.schema.items()
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


def write_table(
    path: Path,
    frame: pl.DataFrame,
    metadata: dict[str, str],
    *,
    max_bytes: int = MAX_BYTES,
) -> str:
    """Write a table in a fresh staging directory, returning its digest.

    The caller installs the parent with its children together. Owner
    metadata is retained so reconstruction keeps the logical schema.

    Returns:
        Digest of the complete physical parent.

    Raises:
        ValueError: A table exceeds the compressed or metadata bound.
    """
    columns = frame.columns
    frame, taskforce_types = encode_taskforce_flags(frame)
    if taskforce_types:
        previous = metadata.get(_STORAGE)
        descriptor = json.dumps(
            {
                "schema": 1,
                "columns": columns,
                "types": taskforce_types,
                "storage": previous,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(descriptor.encode()) > _MAX_META:
            raise ValueError(_INVALID)
        metadata = {**metadata, TASKFORCE_FLAGS: descriptor}
        if previous is not None:
            metadata[_STORAGE] = _column_metadata(previous, frame)
    if not any(is_nested(dtype) for dtype in frame.dtypes):
        digest = _write(path, frame, metadata)
        if path.stat().st_size > max_bytes:
            raise ValueError(_INVALID)
        return digest
    identifier = uuid4().hex
    directory = _generation(path, identifier)
    directory.mkdir(parents=True)
    physical, layout = _split(frame, directory, "")
    previous = metadata.get(_STORAGE)
    envelope = (
        previous
        or parquet_metadata(
            physical,
            contract="scalar-parquet",
        )[_STORAGE]
    )
    descriptor = json.dumps(
        {
            "schema": 1,
            "id": identifier,
            "layout": layout,
            "storage": previous,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(descriptor.encode()) > _MAX_META:
        raise ValueError(_INVALID)
    digest = _write(
        path,
        physical,
        {
            **metadata,
            _STORAGE: _column_metadata(envelope, physical),
            RELATIONS: descriptor,
        },
    )
    if (
        path.stat().st_size
        + sum(child.stat().st_size for child in directory.iterdir())
        > max_bytes
    ):
        raise ValueError(_INVALID)
    _sync(directory)
    _sync(directory.parent)
    return digest


def _physical(
    stream: BinaryIO,
    metadata: dict[str, str],
    max_rows: int,
) -> pl.DataFrame:
    """Validate the physical columns of a normalized table.

    Returns:
        The scalar table with its stored Enum declarations restored.

    Raises:
        ValueError: Data exceeds the physical schema or row bound.
    """
    declared = json.loads(metadata.get(_STORAGE, "{}")).get("columns", {})
    frame = restore_assessment_schema(
        pl.read_parquet(stream, n_rows=max_rows + 1),
        declared,
    )
    validate_parquet_metadata(metadata, frame, allow_legacy=False)
    if frame.height > max_rows or any(
        is_nested(dtype) for dtype in frame.dtypes
    ):
        raise ValueError(_INVALID)
    return frame


def _join(
    parent: pl.DataFrame,
    child: pl.DataFrame,
    name: str,
    spec: dict,
) -> pl.DataFrame:
    """Check child keys and restore their original order.

    Returns:
        Parent with the logical list or struct column restored.

    Raises:
        ValueError: Keys or positions disagree with their parent rows.
    """
    marker = spec["marker"]
    if (
        child.schema.get(_PARENT) != pl.UInt32
        or child.filter(
            pl.col(_PARENT).is_null() | (pl.col(_PARENT) >= parent.height),
        ).height
    ):
        raise ValueError(_INVALID)
    fields = spec["fields"]
    if spec["kind"] == "struct":
        values = child.select(_PARENT, pl.struct(fields).alias(name))
        merged = parent.join(
            values,
            left_on=_ROW,
            right_on=_PARENT,
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        if merged.filter(pl.col(marker) != pl.col(name).is_not_null()).height:
            raise ValueError(_INVALID)
        return merged.drop(marker)

    value = (
        pl.col(_VALUE)
        if fields is None
        else (pl.when(pl.col(_PRESENT)).then(pl.struct(fields)))
    )
    positions = pl.col(_POSITION)
    dtype = pl.List(child.select(value.alias(_VALUE)).schema[_VALUE])
    values = child.group_by(_PARENT).agg(
        value.sort_by(_POSITION).alias(name),
        positions.sort().alias(_POSITIONS),
    )
    merged = parent.join(
        values,
        left_on=_ROW,
        right_on=_PARENT,
        how="left",
        validate="1:1",
        maintain_order="left",
    )
    empty_positions = pl.lit([], dtype=pl.List(pl.UInt32))
    if merged.filter(
        pl.col(_POSITIONS).fill_null(empty_positions)
        != pl.int_ranges(0, pl.col(marker).fill_null(0), dtype=pl.UInt32),
    ).height:
        raise ValueError(_INVALID)
    result = (
        pl
        .when(pl.col(marker).is_null())
        .then(pl.lit(None, dtype=dtype))
        .otherwise(pl.col(name).fill_null(pl.lit([], dtype=dtype)))
    )
    if spec["width"] is not None:
        result = result.cast(pl.Array(dtype.inner, spec["width"]))
    return merged.with_columns(result.alias(name)).drop(marker, _POSITIONS)


def _restore(
    frame: pl.DataFrame,
    directory: Path,
    layout: dict,
    budget: list[int],
    depth: int = 0,
) -> pl.DataFrame:
    """Read recursively linked children under the parent's lease.

    Returns:
        Rows in their original column order.

    Raises:
        ValueError: A child violates its key, digest, or storage bounds.
    """
    if not layout:
        return frame
    if depth >= _MAX_DEPTH or not frame[_ROW].equals(
        pl.int_range(0, frame.height, dtype=pl.UInt32, eager=True),
    ):
        raise ValueError(_INVALID)
    for name, relation in layout["relations"].items():
        filename = relation["file"]
        if not isinstance(filename, str) or _CHILD.fullmatch(filename) is None:
            raise ValueError(_INVALID)
        count = frame[relation["marker"]].cast(pl.UInt64).sum() or 0
        if not 0 <= count <= _MAX_ROWS:
            raise ValueError(_INVALID)
        with open_regular(directory / filename, budget[0]) as stream:
            budget[0] -= os.fstat(stream.fileno()).st_size
            if (
                hashlib.file_digest(stream, "sha256").hexdigest()
                != relation["sha256"]
            ):
                raise ValueError(_INVALID)
            stream.seek(0)
            child = _physical(stream, _metadata(stream), count)
        child = _restore(
            child,
            directory,
            relation["layout"],
            budget,
            depth + 1,
        )
        frame = _join(frame, child, name, relation)
    return frame.select(layout["columns"])


def _restore_memberships(
    frame: pl.DataFrame,
    metadata: dict[str, str],
) -> tuple[pl.DataFrame, dict[str, str]]:
    """Restore membership lists and their original storage metadata.

    Returns:
        Original rows and owner-facing metadata.

    Raises:
        ValueError: The layout or the stored flags are invalid.
    """
    encoded = metadata.get(TASKFORCE_FLAGS)
    if encoded is None:
        return frame, metadata
    if len(encoded.encode()) > _MAX_META:
        raise ValueError(_INVALID)
    descriptor = json.loads(encoded)
    if (
        not isinstance(descriptor, dict)
        or set(descriptor) != {"schema", "columns", "types", "storage"}
        or descriptor["schema"] != 1
    ):
        raise ValueError(_INVALID)
    columns, types, storage = (
        descriptor["columns"],
        descriptor["types"],
        descriptor["storage"],
    )
    if (
        not isinstance(columns, list)
        or not all(isinstance(name, str) for name in columns)
        or not isinstance(types, dict)
        or not all(isinstance(dtype, str) for dtype in types.values())
        or not isinstance(storage, str | None)
    ):
        raise ValueError(_INVALID)
    try:
        frame = restore_taskforce_flags(frame, columns, types)
    except pl.exceptions.PolarsError as error:
        raise ValueError(_INVALID) from error
    logical = dict(metadata)
    logical.pop(TASKFORCE_FLAGS)
    if storage is None:
        logical.pop(_STORAGE, None)
    else:
        logical[_STORAGE] = storage
    validate_parquet_metadata(logical, frame)
    return frame, logical


def read_table(
    path: Path,
    stream: BinaryIO,
    *,
    max_rows: int = _MAX_ROWS,
    max_bytes: int = MAX_BYTES,
) -> tuple[pl.DataFrame, dict[str, str]]:
    """Read a pinned Parquet parent and any child rows.

    Returns:
        Logical rows and the metadata expected by their owner.

    Raises:
        ValueError: A relationship or its saved metadata is invalid.
    """
    metadata = _metadata(stream)
    layout = _layout(metadata)
    if layout is None:
        frame = (
            _physical(stream, metadata, max_rows)
            if TASKFORCE_FLAGS in metadata and _STORAGE in metadata
            else pl.read_parquet(stream, n_rows=max_rows + 1)
        )
        return _restore_memberships(frame, metadata)
    physical = _physical(stream, metadata, max_rows)
    directory = _generation(path, layout["id"])
    if directory.is_symlink():
        raise ValueError(_INVALID)
    try:
        frame = _restore(
            physical,
            directory,
            layout["layout"],
            [max_bytes - os.fstat(stream.fileno()).st_size],
        )
    except (
        KeyError,
        TypeError,
        AttributeError,
        pl.exceptions.PolarsError,
    ) as error:
        raise ValueError(_INVALID) from error
    logical = {
        key: value for key, value in metadata.items() if key != RELATIONS
    }
    if layout["storage"] is None:
        logical.pop(_STORAGE)
    else:
        logical[_STORAGE] = layout["storage"]
    validate_parquet_metadata(logical, frame)
    return _restore_memberships(frame, logical)


@contextmanager
def stage_table(  # ruff: ignore[too-many-arguments]
    path: Path,
    frame: pl.DataFrame,
    metadata: dict[str, str],
    *,
    max_bytes: int = MAX_BYTES,
    mode: int = 0o600,
    staging: Path | None = None,
) -> Iterator[Path]:
    """Stage a complete table on the destination filesystem.

    Yields:
        An unpublished file ready for verification and installation.
    """
    with TemporaryDirectory(
        dir=staging if staging is not None else staging_directory(path),
        prefix=".parquet-",
    ) as directory:
        staged = Path(directory) / path.name
        write_table(staged, frame, metadata, max_bytes=max_bytes)
        staged.chmod(mode)
        yield staged


def install_table(staged: Path, path: Path) -> None:
    """Select staged children and their parent atomically."""
    children = _children(staged)
    root = _root(path)
    descriptor = _lease(root, writing=True, create=children is not None)
    lock_context = (
        os.fdopen(descriptor, "rb")
        if descriptor is not None
        else nullcontext()
    )
    with lock_context as lock:
        if lock is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            previous = _children(path) if lock is not None else None
        except pl.exceptions.PolarsError:
            previous = None
        if children is not None:
            target = _generation(path, children.name[-32:])
            if previous == target:
                # This immutable set is already published.
                return
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            children.replace(target)
            _sync(root)
        staged.replace(path)
        _sync(path.parent)
        if previous is not None:
            shutil.rmtree(previous)


def remove_table(path: Path) -> None:
    """Retire a table and its children after active readers are done."""
    descriptor = _lease(_root(path), writing=True)
    if descriptor is None:
        path.unlink(missing_ok=True)
        return
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        children = _children(path)
        path.unlink(missing_ok=True)
        if children is not None:
            shutil.rmtree(children)


def link_table(source: Path, destination: Path) -> None:
    """Copy a complete immutable table using hard links."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        dir=destination.parent,
        prefix=".parquet-link-",
    ) as directory:
        staged = Path(directory) / destination.name
        with open_table(source, MAX_BYTES) as stream:
            os.link(source, staged, follow_symlinks=False)
            initial = os.fstat(stream.fileno())
            linked = staged.stat(follow_symlinks=False)
            if (initial.st_dev, initial.st_ino) != (
                linked.st_dev,
                linked.st_ino,
            ):
                staged.unlink()
                with staged.open("xb") as target:
                    shutil.copyfileobj(stream, target)
                    target.flush()
                    os.fsync(target.fileno())
                stream.seek(0)
            # The source's children stay pinned until linked.
            layout = _layout(_metadata(stream))
            if layout is not None:
                children = _generation(source, layout["id"])
                target = _generation(staged, layout["id"])
                target.mkdir(parents=True)
                for path in children.iterdir():
                    os.link(path, target / path.name, follow_symlinks=False)
                _sync(target)
                _sync(target.parent)
        install_table(staged, destination)
