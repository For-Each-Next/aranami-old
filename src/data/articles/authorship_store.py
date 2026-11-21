"""Retain listing-time authorship in two tables with one selector.

Save successful batches so historical backfills resume from saved
listings. Corruption and size overflow preserve the durable evidence.

Older token-count observations remain readable with unknown byte counts
and creation revision IDs. Earlier byte scores keep their original
contract and an unknown eligible-source total. Only current evidence
supplies the complete denominator after independent recollection.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from uuid import uuid4

import polars as pl

from data.articles.scope import retain_active
from data.paths import flat_root
from data.reports import ReportResult, ReportStore
from shared.support.parquet import (
    report_parquet_activity,
    validate_parquet_metadata,
)

if TYPE_CHECKING:
    from pathlib import Path

CONTRACT = "wikiwho-zh:listing-range-nonref-bytes-v4"
FALLBACK_CONTRACT = "wikiwho-zh:listing-range-token-bytes-v1"
CURRENT_CONTRACTS = frozenset({CONTRACT, FALLBACK_CONTRACT})
_BYTE_CONTRACTS = frozenset({
    "wikiwho-zh:listing-range-nonref-bytes-v3",
    CONTRACT,
    FALLBACK_CONTRACT,
})
KEY = ["page_id", "date", "grade", "action", "contract"]
CONTRIBUTOR_SCHEMA = {
    "editor": pl.String,
    "name": pl.String,
    "tokens": pl.UInt32,
    "bytes": pl.UInt32,
    "characters": pl.UInt32,
    "prose_characters": pl.UInt32,
    "raw_bytes": pl.UInt32,
    "share": pl.Float64,
}
SCHEMA = {
    "page_id": pl.Int64,
    "date": pl.Date,
    "grade": pl.String,
    "action": pl.String,
    "contract": pl.String,
    "eligible_bytes": pl.UInt32,
    "listing_revision": pl.Int64,
    "creation_revision": pl.Int64,
    "cutoff": pl.Datetime("us", "UTC"),
    "creation": pl.Datetime("us", "UTC"),
    "fetched_at": pl.Datetime("us", "UTC"),
    "authors": pl.List(pl.String),
    "contributors": pl.List(pl.Struct(CONTRIBUTOR_SCHEMA)),
}
LISTING_SCHEMA = {
    key: dtype
    for key, dtype in SCHEMA.items()
    if key not in {"authors", "contributors"}
}
LISTING_CONTRIBUTOR_SCHEMA = {
    **{key: SCHEMA[key] for key in KEY},
    **CONTRIBUTOR_SCHEMA,
}
_MAX_ROWS = 20_000
_MAX_BYTES = 32 * 1024 * 1024
_SHARE_TOLERANCE = 1e-9
MAIN_SHARE_THRESHOLD = 0.33
MAIN_MIN_CHARACTERS = 500
SIGNIFICANT_SHARE_THRESHOLD = 0.1
UTF8_MAX_BYTES_PER_CHARACTER = 4


def restore_contributor_characters(frame: pl.DataFrame) -> pl.DataFrame:
    """Add measure fields to earlier byte evidence.

    Returns:
        The updated frame if its contributor type matched.
    """
    previous = pl.List(
        pl.Struct({
            key: dtype
            for key, dtype in CONTRIBUTOR_SCHEMA.items()
            if key != "prose_characters"
        }),
    )
    if frame.schema.get("contributors") == previous:
        return frame.cast({"contributors": SCHEMA["contributors"]})
    old = pl.List(
        pl.Struct({
            key: dtype
            for key, dtype in CONTRIBUTOR_SCHEMA.items()
            if key not in {"characters", "prose_characters", "raw_bytes"}
        }),
    )
    if frame.schema.get("contributors") != old:
        return frame
    restored = frame.cast({"contributors": SCHEMA["contributors"]})
    if "contract" not in frame.columns:
        return restored
    return restored.with_columns(
        pl
        .when(pl.col("contract").str.contains("token-bytes", literal=True))
        .then(
            pl.col("contributors").list.eval(
                pl.element().struct.with_fields(
                    pl.element().struct.field("bytes").alias("raw_bytes"),
                ),
            ),
        )
        .otherwise(pl.col("contributors"))
        .alias("contributors"),
    )


def complete_contributor_evidence(frame: pl.DataFrame) -> pl.DataFrame:
    """Select observations with the new contributor measures.

    Returns:
        Results with both measures for all significant editors. Partial
        evidence remains eligible for bounded collection retries.
    """
    contributor = pl.element().struct
    return frame.filter(
        ~pl
        .col("contributors")
        .list.eval(
            (
                contributor.field("raw_bytes").is_null()
                | contributor.field("prose_characters").is_null()
            )
            & (contributor.field("share") >= SIGNIFICANT_SHARE_THRESHOLD),
        )
        .list.any(),
    )


def retain_raw_binding(
    previous: pl.DataFrame,
    refreshed: pl.DataFrame,
    keys: list[str],
) -> pl.DataFrame:
    """Keep the existing byte-proof identity when adding prose counts.

    Returns:
        Refreshed evidence using the original byte observation time
        when the retained raw facts agree.
    """
    raw = pl.col("contributors").list.eval(
        pl.element().struct.with_fields(
            pl.lit(None, dtype=pl.UInt32).alias("prose_characters"),
        ),
    )
    saved = previous.select(
        *keys,
        raw.alias("_prior_raw"),
        pl.col("fetched_at").alias("_prior_at"),
        pl.col("contributors").alias("_prior_contributors"),
    )
    same_source = raw.eq_missing(pl.col("_prior_raw"))
    prose_missing = (
        pl
        .col("contributors")
        .list.eval(pl.element().struct.field("prose_characters").is_null())
        .list.all()
    )
    return (
        refreshed
        .join(saved, on=keys, how="left", validate="m:1", nulls_equal=True)
        .with_columns(
            pl
            .when(same_source)
            .then(pl.col("_prior_at"))
            .otherwise(pl.col("fetched_at"))
            .alias("fetched_at"),
            pl
            .when(same_source & prose_missing)
            .then(pl.col("_prior_contributors"))
            .otherwise(pl.col("contributors"))
            .alias("contributors"),
        )
        .select(refreshed.columns)
    )


def preferred_observations(
    frame: pl.DataFrame,
    key: list[str],
) -> pl.DataFrame:
    """Keep the exact score when a later backfill can only use fallback.

    Returns:
        The latest preferred evidence for each supplied identity.
    """
    return frame.sort(pl.col("contract") == CONTRACT, "fetched_at").unique(
        subset=key,
        keep="last",
        maintain_order=True,
    )


def _validate(frame: pl.DataFrame) -> None:
    """Reject incomplete observations and unsafe names before reuse.

    Raises:
        ValueError: Stored evidence violates the storage contract.
    """
    if (
        frame.schema != pl.Schema(SCHEMA)
        or frame.height > _MAX_ROWS
        or frame.estimated_size() > _MAX_BYTES * 4
    ):
        message = "Invalid authorship evidence schema or size."
        raise ValueError(message)
    invalid = frame.filter(
        pl.any_horizontal(
            pl.exclude(
                "creation_revision",
                "eligible_bytes",
                "authors",
            ).is_null(),
        )
        | (
            ~pl.col("contract").is_in(CURRENT_CONTRACTS)
            & pl.col("authors").is_null()
        )
        | (pl.col("page_id") <= 0)
        | (pl.col("listing_revision") <= 0)
        | (
            pl.col("contract").is_in(_BYTE_CONTRACTS)
            & (
                pl.col("creation_revision").is_null()
                | (pl.col("creation_revision") <= 0)
            )
        )
        | (
            pl.col("contract").is_in(CURRENT_CONTRACTS)
            & (
                pl.col("eligible_bytes").is_null()
                | (pl.col("eligible_bytes") == 0)
            )
        )
        | (pl.col("creation") >= pl.col("cutoff"))
        | (pl.col("fetched_at") < pl.col("cutoff"))
        | (
            pl.col("cutoff")
            != pl
            .col("date")
            .cast(pl.Datetime("us"))
            .dt.replace_time_zone("UTC")
            + pl.duration(days=1)
        )
        | ~pl.col("contract").str.len_bytes().is_between(1, 200)
        | ~pl.col("grade").is_in(["FA", "FL", "GA", "A", "AL", "Bplus"])
        | (pl.col("action") != "added")
        | (
            pl.col("authors").is_not_null()
            & ~pl.col("authors").list.len().is_between(1, 10_000)
        )
        | ~pl.col("contributors").list.len().is_between(1, 10_000),
    )
    names = (
        frame
        .filter(pl.col("authors").is_not_null())
        .select("authors")
        .explode("authors", empty_as_null=True)
        .filter(
            pl.col("authors").is_null()
            | ~pl.col("authors").str.len_bytes().is_between(1, 1000)
            | pl.col("authors").str.contains(r"[\[\]{}|<>\x00-\x1f\x7f]"),
        )
    )
    if (
        not invalid.is_empty()
        or not names.is_empty()
        or frame.select(KEY).n_unique() != frame.height
    ):
        message = "Invalid authorship evidence evidence."
        raise ValueError(message)
    if frame.is_empty():
        return
    contributors = (
        frame
        .with_row_index("_row")
        .select("_row", "contract", "eligible_bytes", "contributors")
        .explode("contributors", empty_as_null=True)
        .unnest("contributors")
        .with_columns(
            pl
            .when(pl.col("contract").is_in(_BYTE_CONTRACTS))
            .then(pl.col("bytes"))
            .otherwise(pl.col("tokens"))
            .alias("_score"),
        )
        .with_columns(
            pl
            .when(pl.col("contract").is_in(CURRENT_CONTRACTS))
            .then(pl.col("eligible_bytes"))
            .otherwise(pl.col("_score").sum().over("_row"))
            .alias("_total"),
        )
    )
    bad = contributors.filter(
        pl.any_horizontal(pl.col("editor", "tokens", "share").is_null())
        | ~pl.col("editor").str.contains(r"^([1-9][0-9]*|0\|[^\x00-\x20]+)$")
        | (pl.col("tokens") == 0)
        | (pl.col("characters") > pl.col("bytes")).fill_null(value=False)
        | (pl.col("bytes") > pl.col("raw_bytes")).fill_null(value=False)
        | ~pl.col("share").is_finite()
        | ~pl.col("share").is_between(0, 1)
        | (~pl.col("contract").is_in(_BYTE_CONTRACTS) & (pl.col("share") <= 0))
        | pl.col("_score").is_null()
        | (pl.col("_score").sum().over("_row") <= 0)
        | (pl.col("_score").sum().over("_row") > pl.col("_total"))
        | (
            pl.col("name").is_not_null()
            & (
                ~pl.col("name").str.len_bytes().is_between(1, 1000)
                | pl.col("name").str.strip_chars().eq("")
                | pl.col("name").str.contains(r"[\[\]{}|<>\x00-\x1f\x7f]")
            )
        )
        | (
            (pl.col("share") - pl.col("_score") / pl.col("_total")).abs()
            > _SHARE_TOLERANCE
        ),
    )
    top = (
        contributors
        .filter(
            pl.col("_score") == pl.col("_score").max().over("_row"),
        )
        .group_by("_row")
        .agg(
            pl.col("name").unique().sort().alias("_authors"),
            pl.col("name").is_null().any().alias("_unknown_author"),
        )
        .with_columns(
            pl
            .when(pl.col("_unknown_author"))
            .then(pl.lit(None, dtype=pl.List(pl.String)))
            .otherwise(pl.col("_authors"))
            .alias("_authors"),
        )
    )
    mismatch = (
        frame
        .with_row_index("_row")
        .join(top, on="_row")
        .filter(
            ~pl.col("authors").eq_missing(pl.col("_authors")),
        )
    )
    if not bad.is_empty() or not mismatch.is_empty():
        message = "Authorship evidence contributor evidence is inconsistent."
        raise ValueError(message)


def _legacy(path: Path) -> pl.DataFrame:
    """Read retained successes, preserving damaged data for recovery.

    Args:
        path: Durable runtime path outside the source generation.

    Returns:
        Validated evidence, or an empty frame on first use.

    Raises:
        OSError: Storage is unsafe or unreadable.
        ValueError: Existing evidence is corrupt or exceeds its bounds.
    """
    if path.is_symlink() or path.parent.is_symlink():
        message = "Authorship storage requires regular paths."
        raise OSError(message)
    if not path.exists():
        return pl.DataFrame(schema=SCHEMA)
    if not path.is_file():
        message = "Authorship storage requires a regular file."
        raise OSError(message)
    if path.stat().st_size > _MAX_BYTES:
        message = "Authorship data exceeds its file bound."
        raise ValueError(message)
    try:
        with path.open("rb") as stream:
            metadata = pl.read_parquet_metadata(stream)
            stream.seek(0)
            frame = pl.read_parquet(stream, n_rows=_MAX_ROWS + 1)
        validate_parquet_metadata(
            metadata,
            frame,
            contract="article-authorship",
        )
    except pl.exceptions.PolarsError as error:
        message = "Authorship data is not readable Parquet."
        raise ValueError(message) from error
    frame = restore_contributor_characters(frame)
    legacy = dict(SCHEMA)
    legacy.pop("eligible_bytes")
    legacy.pop("creation_revision")
    legacy["contributors"] = pl.List(
        pl.Struct({
            name: dtype
            for name, dtype in CONTRIBUTOR_SCHEMA.items()
            if name
            not in {"bytes", "characters", "prose_characters", "raw_bytes"}
        }),
    )
    if frame.schema == pl.Schema(legacy):
        frame = frame.with_columns(
            pl.lit(None, dtype=pl.Int64).alias("creation_revision"),
            pl.lit(None, dtype=pl.UInt32).alias("eligible_bytes"),
            pl
            .col("contributors")
            .list.eval(
                pl.element().struct.with_fields(
                    pl.lit(None, dtype=pl.UInt32).alias("bytes"),
                ),
            )
            .cast(SCHEMA["contributors"]),
        ).select(list(SCHEMA))
    elif frame.schema == pl.Schema({
        key: value for key, value in SCHEMA.items() if key != "eligible_bytes"
    }):
        frame = frame.with_columns(
            pl.lit(None, dtype=pl.UInt32).alias("eligible_bytes"),
        ).select(list(SCHEMA))
    _validate(frame)
    report_parquet_activity(path, "source_loaded")
    return frame


def _store(path: Path) -> ReportStore:
    """Locate the shared listing selector or a caller's custom store.

    Returns:
        A report store with the listing-evidence namespace.
    """
    root = path.parent
    if (
        root.name == "parsed"
        and root.parent.name == "data"
        and path.name == "article-authorship.parquet"
    ):
        return ReportStore(root.parent / "shared")
    return ReportStore(
        root,
        flat_name=path.stem if flat_root(root) == root else None,
    )


def _load(
    path: Path,
    store: ReportStore,
    *,
    locked: bool = False,
) -> pl.DataFrame:
    """Reconstruct the established in-memory view from a selected pair.

    Returns:
        Validated listings with contributors and their leading authors.

    Raises:
        ValueError: A selected table or relationship is invalid.
    """
    bundle = store.read(path.stem, locked=locked)
    if bundle is None:
        return _legacy(path)
    listings = bundle.tables.get("listings")
    contributors = bundle.tables.get("contributors")
    if (
        listings is None
        or contributors is None
        or listings.schema != pl.Schema(LISTING_SCHEMA)
        or contributors.schema != pl.Schema(LISTING_CONTRIBUTOR_SCHEMA)
        or not contributors.join(
            listings.select(KEY),
            on=KEY,
            how="anti",
        ).is_empty()
    ):
        message = "Invalid listing authorship tables."
        raise ValueError(message)
    names = pl.col("name").filter(pl.col("_score") == pl.col("_score").max())
    details = (
        contributors
        .with_columns(
            pl
            .when(pl.col("contract").is_in(_BYTE_CONTRACTS))
            .then(pl.col("bytes"))
            .otherwise(pl.col("tokens"))
            .alias("_score"),
        )
        .group_by(KEY, maintain_order=True)
        .agg(
            pl.struct(list(CONTRIBUTOR_SCHEMA)).alias("contributors"),
            names.unique().sort().alias("authors"),
        )
        .with_columns(
            pl.when(
                ~pl
                .col("authors")
                .list.eval(pl.element().is_null())
                .list.any(),
            ).then(pl.col("authors")),
        )
    )
    frame = listings.join(
        details,
        on=KEY,
        how="left",
        validate="1:1",
        maintain_order="left",
    ).select(list(SCHEMA))
    _validate(frame)
    return frame


def load(path: Path) -> pl.DataFrame:
    """Read the selected authorship generation or its retained original.

    Returns:
        Validated evidence, or a typed empty frame before first use.
    """
    return _load(path, _store(path))


def normalize_storage(path: Path) -> bool:
    """Retain the original observations in a verified scalar generation.

    Returns:
        Whether the complete legacy file is represented by the selector.

    Raises:
        ValueError: The selected records differ from the original.
    """
    store = _store(path)
    key = path.stem
    with store.locked(key):
        if not path.is_file():
            return False
        original = _legacy(path)
        if not store.has_data(key):
            _write(store, key, original)
        if not _load(path, store, locked=True).equals(original):
            message = (
                "The selected listing evidence differs from the original."
            )
            raise ValueError(message)
    return True


def _write(store: ReportStore, key: str, frame: pl.DataFrame) -> None:
    """Select a listing and contributor pair under the caller's lock."""
    tables = {
        "listings": frame.select(list(LISTING_SCHEMA)),
        "contributors": (
            frame
            .select(*KEY, "contributors")
            .explode("contributors", empty_as_null=False)
            .unnest("contributors")
        ),
    }
    store.write(
        key,
        ReportResult(family="article-authorship", tables=tables),
        "",
        run_id=uuid4().hex,
        started_at=dt.datetime.now(dt.UTC),
        target={"site": "zhwiki", "title": "Article listing authorship"},
        locked=True,
    )


def save(
    path: Path,
    refreshed: pl.DataFrame,
) -> None:
    """Merge successes under a lock and atomically retain every event.

    Args:
        path: Durable runtime path.
        refreshed: Successful, complete listing evidence.

    Raises:
        OSError: Storage is unsafe or unavailable.
        ValueError: Evidence exceeds its contract.
    """  # ruff: ignore[docstring-extraneous-exception]
    _validate(refreshed)
    if path.is_symlink() or path.parent.is_symlink():
        message = "Authorship evidence requires regular paths."
        raise OSError(message)
    store = _store(path)
    key = path.stem
    with store.locked(key):
        previous = _load(path, store, locked=True)
        refreshed = retain_raw_binding(
            previous,
            refreshed,
            [*KEY, "listing_revision", "eligible_bytes"],
        )
        merged = (
            pl
            .concat([previous, refreshed])
            .sort("fetched_at", maintain_order=True)
            .unique(subset=KEY, keep="last", maintain_order=True)
        )
        merged = retain_active(merged, path)
        _validate(merged)
        if store.has_data(key) and merged.equals(previous):
            return
        _write(store, key, merged)
