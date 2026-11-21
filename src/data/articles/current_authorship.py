"""Retain current B-class membership and listing-time attribution.

The selected bundle keeps the complete current B/BL cohort, successful
listing-time revision evidence and durable retry order. Exact talk
identities bind cached listing dates and article cutoffs; later subject
edits reuse them without repeating source requests.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from uuid import uuid4

import polars as pl

from data.articles import rating_history as assessment_inference
from data.articles.authorship_store import (
    CONTRIBUTOR_SCHEMA,
    complete_contributor_evidence,
    restore_contributor_characters,
    retain_raw_binding,
)
from data.articles.storage import DEFAULT_ROOT
from data.reports import ReportResult, ReportStore
from shared.assessment_profiles import assessment_profile

if TYPE_CHECKING:
    from pathlib import Path

KEY = ["page_id", "revision_id"]
GRADES = ("B", "BL", "C", "CL", "Start", "List", "Stub", "SL", "Unassessed")
CONTRACT = "wikiwho-zh:current-revision-nonref-bytes-v1"
FALLBACK_CONTRACT = "wikiwho-zh:current-revision-token-bytes-v1"
CONTRACTS = (CONTRACT, FALLBACK_CONTRACT)
LISTING_KEY = [
    "page_id",
    "talk_page_id",
    "talk_revision",
    "grade",
    "banner_contract",
]
LISTING_SCHEMA = {
    "article_timestamp": pl.Datetime("us", "UTC"),
    "banner_contract": pl.String,
    "talk_page_id": pl.Int64,
    "talk_revision": pl.Int64,
    "listing_talk_revision": pl.Int64,
    "listing_timestamp": pl.Datetime("us", "UTC"),
}
MEMBER_SCHEMA = {
    "page_id": pl.Int64,
    "revision_id": pl.Int64,
    "title": pl.String,
    "grade": pl.String,
    "observed_at": pl.Datetime("us", "UTC"),
    **LISTING_SCHEMA,
}
EVIDENCE_SCHEMA = {
    "page_id": pl.Int64,
    "revision_id": pl.Int64,
    "contract": pl.String,
    "eligible_bytes": pl.UInt32,
    "revision_timestamp": pl.Datetime("us", "UTC"),
    "creation_revision": pl.Int64,
    "creation_timestamp": pl.Datetime("us", "UTC"),
    "fetched_at": pl.Datetime("us", "UTC"),
    "contributors": pl.List(pl.Struct(CONTRIBUTOR_SCHEMA)),
}
ATTEMPT_SCHEMA = {
    "page_id": pl.Int64,
    "revision_id": pl.Int64,
    "attempted_at": pl.Datetime("us", "UTC"),
}
TARGET_SCHEMA = {
    key: MEMBER_SCHEMA[key]
    for key in ("page_id", "revision_id", "title", "grade", "observed_at")
}
_SCHEMAS = {
    "targets": TARGET_SCHEMA,
    "members": MEMBER_SCHEMA,
    "evidence": EVIDENCE_SCHEMA,
    "attempts": ATTEMPT_SCHEMA,
}
_KEY = "articles/current-authorship/b-class"
_FLAT_NAME = "authorship"
_MAX_ROWS = 100_000
_MAX_BYTES = 128 * 1024 * 1024
_SHARE_TOLERANCE = 1e-9


def prepare_membership(
    membership: pl.DataFrame,
    observed_at: dt.datetime,
    inference: pl.DataFrame | None = None,
    *,
    banner_contract: str = "unavailable",
) -> pl.DataFrame:
    """Select current mainspace B articles and B-class lists.

    Args:
        membership: Complete current replica rows with revision IDs.
        observed_at: Actual UTC time of the membership observation.
        inference: Saved literal talk-range proofs, when available.
        banner_contract: Literal parser version used to validate reuse.

    Returns:
        Canonical B/BL identities with proved listing timestamps and
        pending article cutoffs. Unknown history remains nullable.
    """
    profile = assessment_profile("zhwiki", "电子游戏")
    proofs = (
        inference
        if inference is not None
        else pl.DataFrame(schema=assessment_inference.INFERENCE_SCHEMA)
    )
    complete = (pl.col("banner_transition_status") == "proven") | (
        pl.col("reason") == "earliest_visible"
    )
    proofs = proofs.select(
        pl.col("page_id").cast(pl.Int64),
        pl.col("talk_page_id").cast(pl.Int64),
        pl.col("scanned_talk_rev_id").cast(pl.Int64).alias("talk_revision"),
        profile.expression("class", "class", preserve_unknown=False).alias(
            "grade",
        ),
        "parser_version",
        pl
        .when(complete)
        .then(pl.col("banner_entry_talk_rev_id"))
        .cast(pl.Int64)
        .alias("listing_talk_revision"),
        pl
        .when(complete)
        .then(pl.col("banner_entry_timestamp"))
        .alias("listing_timestamp"),
    )
    return (
        membership
        .with_columns(
            profile.expression(
                "pa_class",
                "class",
                preserve_unknown=False,
            ).alias("grade"),
        )
        .filter(
            (pl.col("page_namespace") == 0)
            & (pl.col("page_is_redirect") == 0)
            & pl.col("grade").is_in(GRADES),
        )
        .select(
            "page_id",
            pl.lit(None, dtype=pl.Int64).alias("revision_id"),
            *(
                (
                    pl.col(name)
                    if name in membership.columns
                    else pl.lit(None, dtype=pl.Int64)
                )
                .cast(pl.Int64)
                .alias(name)
                for name in ("talk_page_id", "talk_revision")
            ),
            pl.col("page_title").alias("title"),
            "grade",
            pl
            .lit(observed_at.isoformat())
            .str.to_datetime(time_zone="UTC")
            .alias("observed_at"),
        )
        .join(
            proofs,
            on=[key for key in LISTING_KEY if key != "banner_contract"],
            how="left",
            validate="1:1",
        )
        .with_columns(
            pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias(
                "article_timestamp",
            ),
            pl.concat_str(
                pl.lit(banner_contract),
                "parser_version",
                separator=":",
            ).alias("banner_contract"),
        )
        .select(list(MEMBER_SCHEMA))
        .cast(MEMBER_SCHEMA)
        .sort("page_id")
    )


def _validate(tables: dict[str, pl.DataFrame]) -> None:
    """Validate bounded revision identities and contributor shares.

    Raises:
        ValueError: Retained current attribution is incomplete or
            corrupt.
    """
    if set(tables) != set(_SCHEMAS):
        message = "Current authorship requires all three durable tables."
        raise ValueError(message)
    for name, schema in _SCHEMAS.items():
        frame = tables[name]
        if (
            frame.schema != pl.Schema(schema)
            or frame.height > _MAX_ROWS
            or frame.estimated_size() > _MAX_BYTES
            or frame.select(KEY).n_unique() != frame.height
            or frame.filter(
                pl.col("page_id").is_null()
                | (
                    pl.col("revision_id").is_null()
                    if name == "evidence"
                    else pl.lit(value=False)
                )
                | (pl.col("page_id") <= 0)
                | (pl.col("revision_id") <= 0),
            ).height
        ):
            message = "Invalid current authorship table schema or identity."
            raise ValueError(message)
    targets = tables["targets"]
    profile = assessment_profile("zhwiki", "电子游戏")
    if (
        targets["page_id"].n_unique() != targets.height
        or targets.filter(
            pl.any_horizontal(pl.all().is_null())
            | ~pl.col("grade").is_in([
                label.code for label in profile.classes if label.is_article
            ])
            | ~pl.col("title").str.len_bytes().is_between(1, 4096),
        ).height
    ):
        message = "Invalid current-revision attribution targets."
        raise ValueError(message)
    members, evidence, attempts = (
        tables[name] for name in ("members", "evidence", "attempts")
    )
    if (
        members["page_id"].n_unique() != members.height
        or members.filter(
            pl.any_horizontal(
                pl.col("page_id", "title", "grade", "observed_at").is_null(),
            )
            | (
                pl.col("listing_timestamp").is_null()
                != pl.col("listing_talk_revision").is_null()
            )
            | (
                pl.col("revision_id").is_not_null()
                & pl.col("listing_timestamp").is_null()
            )
            | (
                pl.col("listing_timestamp").is_not_null()
                & pl.any_horizontal(
                    pl.col(
                        "talk_page_id",
                        "talk_revision",
                        "banner_contract",
                    ).is_null(),
                )
            )
            | (pl.col("talk_page_id") <= 0)
            | (pl.col("talk_revision") <= 0)
            | (pl.col("listing_talk_revision") <= 0)
            | (pl.col("article_timestamp") > pl.col("listing_timestamp"))
            | (pl.col("listing_timestamp") > pl.col("observed_at"))
            | (pl.col("listing_talk_revision") > pl.col("talk_revision"))
            | ~pl.col("grade").is_in(GRADES)
            | ~pl.col("title").str.len_bytes().is_between(1, 4096),
        ).height
        or attempts["attempted_at"].null_count()
        or evidence.filter(
            pl.any_horizontal(
                pl.exclude(
                    "creation_revision",
                    "creation_timestamp",
                ).is_null(),
            )
            | (pl.col("creation_revision") <= 0)
            | (pl.col("creation_timestamp") > pl.col("revision_timestamp"))
            | (
                pl.col("creation_revision").is_null()
                != pl.col("creation_timestamp").is_null()
            )
            | ~pl.col("contract").is_in(CONTRACTS)
            | (pl.col("eligible_bytes") <= 0)
            | (pl.col("revision_timestamp") > pl.col("fetched_at"))
            | (pl.col("contributors").list.len() == 0),
        ).height
    ):
        message = "Incomplete current authorship evidence or membership."
        raise ValueError(message)
    if evidence.is_empty():
        return
    contributors = (
        evidence
        .select(*KEY, "eligible_bytes", "contributors")
        .explode("contributors")
        .unnest("contributors")
    )
    if contributors.filter(
        pl.any_horizontal(
            pl.col("editor", "tokens", "bytes", "share").is_null(),
        )
        | ~pl.col("editor").str.contains(r"^([1-9][0-9]*|0\|[^\x00-\x20]+)$")
        | (pl.col("tokens") == 0)
        | (pl.col("characters") > pl.col("bytes")).fill_null(value=False)
        | (pl.col("bytes") > pl.col("raw_bytes")).fill_null(value=False)
        | ~pl.col("share").is_finite()
        | ~pl.col("share").is_between(0, 1)
        | (
            pl.col("bytes").cast(pl.UInt64).sum().over(KEY)
            > pl.col("eligible_bytes")
        )
        | (pl.col("bytes").cast(pl.UInt64).sum().over(KEY) == 0)
        | (
            (
                pl.col("share") - pl.col("bytes") / pl.col("eligible_bytes")
            ).abs()
            > _SHARE_TOLERANCE
        )
        | (
            pl.col("name").is_not_null()
            & (
                ~pl.col("name").str.len_bytes().is_between(1, 1000)
                | pl.col("name").str.strip_chars().eq("")
                | pl.col("name").str.contains(r"[\[\]{}|<>\x00-\x1f\x7f]")
            )
        )
        | pl.struct(*KEY, "editor").is_duplicated(),
    ).height:
        message = "Invalid current authorship contributor shares."
        raise ValueError(message)


def _read(
    store: ReportStore,
    *,
    locked: bool = False,
) -> dict[str, pl.DataFrame]:
    """Read validated state and preserve explicit corruption failures.

    Returns:
        All retained tables, including typed empty first-use tables.

    Raises:
        ValueError: A legacy revision identity is invalid.
    """
    bundle = store.read(_KEY, locked=locked)
    tables = dict(bundle.tables) if bundle is not None else empty_tables()
    tables.setdefault("targets", pl.DataFrame(schema=TARGET_SCHEMA))
    tables["evidence"] = restore_contributor_characters(tables["evidence"])
    legacy_evidence = {
        name: dtype
        for name, dtype in EVIDENCE_SCHEMA.items()
        if name not in {"creation_revision", "creation_timestamp"}
    }
    if tables["evidence"].schema == pl.Schema(legacy_evidence):
        tables["evidence"] = (
            tables["evidence"]
            .with_columns(
                pl.lit(None, dtype=pl.Int64).alias("creation_revision"),
                pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias(
                    "creation_timestamp",
                ),
            )
            .select(list(EVIDENCE_SCHEMA))
        )
    legacy = {
        name: dtype
        for name, dtype in MEMBER_SCHEMA.items()
        if name not in LISTING_SCHEMA
    }
    if tables["members"].schema == pl.Schema(legacy):
        if (
            tables["members"]
            .filter(
                pl.col("revision_id").is_null() | (pl.col("revision_id") <= 0),
            )
            .height
        ):
            message = "Invalid legacy authorship revision identity."
            raise ValueError(message)
        # Old current-revision facts stay reusable by exact oldid, but
        # cannot claim a listing date or establish listing-time credit.
        tables["members"] = (
            tables["members"]
            .with_columns(
                pl.lit(None, dtype=pl.Int64).alias("revision_id"),
                *(
                    pl.lit(None, dtype=dtype).alias(name)
                    for name, dtype in LISTING_SCHEMA.items()
                ),
            )
            .select(list(MEMBER_SCHEMA))
        )
    previous_schema = {
        name: dtype
        for name, dtype in MEMBER_SCHEMA.items()
        if name != "article_timestamp"
    }
    if tables["members"].schema == pl.Schema(previous_schema):
        tables["members"] = (
            tables["members"]
            .join(
                tables["evidence"].select(
                    *KEY,
                    pl.col("revision_timestamp").alias("article_timestamp"),
                ),
                on=KEY,
                how="left",
                validate="1:1",
            )
            .select(list(MEMBER_SCHEMA))
        )
    _validate(tables)
    return tables


def empty_tables() -> dict[str, pl.DataFrame]:
    """Prepare empty observations for a missing current store.

    Returns:
        Every store table with its declared schema.
    """
    return {
        name: pl.DataFrame(schema=schema) for name, schema in _SCHEMAS.items()
    }


def load(runtime: Path) -> dict[str, pl.DataFrame]:
    """Read durable listing-time attribution without contacting sources.

    Args:
        runtime: Toolforge runtime containing the separate current
            store.

    Returns:
        Typed current members, retained revision evidence and retry
        times.
        Each table is empty before its first successful collection.
    """
    return _read(ReportStore(runtime / DEFAULT_ROOT, flat_name=_FLAT_NAME))


def compact_storage(runtime: Path, *, restore: bool = False) -> bool:
    """Copy selected attribution tables to short flat filenames.

    Args:
        runtime: Toolforge runtime with the current authorship bundle.
        restore: Populate the former paths for a rollback.

    Returns:
        Whether the corresponding selector was published.
    """
    store = ReportStore(runtime / DEFAULT_ROOT, flat_name=_FLAT_NAME)
    return store.copy_selection(_KEY, restore=restore)


def checkpoint(  # ruff: ignore[too-many-arguments] - Single atomic checkpoint for the cohort and attempts.
    runtime: Path,
    *,
    members: pl.DataFrame | None = None,
    targets: pl.DataFrame | None = None,
    evidence: pl.DataFrame | None = None,
    attempted: dict[str, int | None] | None = None,
    attempts: pl.DataFrame | None = None,
) -> dict[str, pl.DataFrame]:
    """Atomically retain a cohort or batch of attribution results.

    Args:
        runtime: Toolforge runtime containing the separate current
            store.
        members: Complete B/BL cohort, or none to retain it. Cached
            article cutoffs survive identical nonnull talk, class and
            listing boundaries, including a parser-provenance refresh.
        targets: Current-revision cohort for hourly attribution.
        evidence: Successful exact-revision evidence, when available.
        attempted: Page and revision identity attempted in this pass.
        attempts: Batched attempt times from a collection pass.

    Returns:
        The selected tables, including earlier exact revisions. A failed
        attempt changes retry order and preserves existing evidence.
    """
    store = ReportStore(runtime / DEFAULT_ROOT, flat_name=_FLAT_NAME)
    with store.locked(_KEY):
        tables = _read(store, locked=True)
        previous_tables = tables.copy()
        if members is not None:
            previous = tables["members"]["observed_at"].max()
            latest = members["observed_at"].max()
            if previous is None or latest is None or latest >= previous:
                cutoff_key = [
                    "page_id",
                    "talk_page_id",
                    "grade",
                    "listing_talk_revision",
                    "listing_timestamp",
                ]
                cached = (
                    tables["members"]
                    .filter(
                        pl.all_horizontal(pl.col(cutoff_key).is_not_null()),
                    )
                    .select(
                        *cutoff_key,
                        *(
                            pl.col(name).alias(f"{name}_cached")
                            for name in ("revision_id", "article_timestamp")
                        ),
                    )
                )
                members = (
                    members
                    .join(cached, on=cutoff_key, how="left", validate="1:1")
                    .with_columns(
                        *(
                            pl.coalesce(name, f"{name}_cached").alias(name)
                            for name in ("revision_id", "article_timestamp")
                        ),
                    )
                    .select(list(MEMBER_SCHEMA))
                )
                tables["members"] = members
        if targets is not None:
            previous = tables["targets"]["observed_at"].max()
            latest = targets["observed_at"].max()
            if previous is None or latest is None or latest >= previous:
                tables["targets"] = targets
        if evidence is not None:
            evidence = retain_raw_binding(
                tables["evidence"],
                evidence,
                [*KEY, "contract", "eligible_bytes"],
            )
            tables["evidence"] = (
                pl
                .concat([tables["evidence"], evidence])
                .with_columns(
                    pl
                    .col("creation_revision", "creation_timestamp")
                    .max()
                    .over(KEY),
                )
                .sort(
                    pl.col("contract") == CONTRACT,
                    "fetched_at",
                    maintain_order=True,
                )
                .unique(subset=KEY, keep="last", maintain_order=True)
            )
        if attempted is not None:
            update = pl.DataFrame(
                [{**attempted, "attempted_at": dt.datetime.now(dt.UTC)}],
                schema=ATTEMPT_SCHEMA,
            )
            attempts = (
                update if attempts is None else pl.concat([attempts, update])
            )
        if attempts is not None:
            tables["attempts"] = (
                pl
                .concat([tables["attempts"], attempts])
                .sort("attempted_at")
                .unique(subset=KEY, keep="last", maintain_order=True)
            )
        tables["attempts"] = (
            tables["attempts"]
            .join(
                pl.concat([
                    tables["members"].select(KEY),
                    tables["targets"].select(KEY),
                ]).unique(),
                on=KEY,
                how="semi",
                nulls_equal=True,
            )
            .join(
                complete_contributor_evidence(tables["evidence"]).select(KEY),
                on=KEY,
                how="anti",
                nulls_equal=True,
            )
        )
        if all(
            table.equals(previous_tables[name])
            for name, table in tables.items()
        ):
            return tables
        _validate(tables)
        store.write(
            _KEY,
            ReportResult(family="current-authorship", tables=tables),
            "",
            run_id=uuid4().hex,
            started_at=dt.datetime.now(dt.UTC),
            target={"site": "zhwiki", "title": "B-class authorship"},
            locked=True,
        )
        return tables


def pending(tables: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Order unresolved revisions fairly across restarts.

    Args:
        tables: Validated state from the durable current store.

    Returns:
        Unattempted members in newest listing order, followed by the
        least recently attempted members.
    """
    return (
        tables["members"]
        .filter(pl.col("listing_timestamp").is_not_null())
        .join(
            complete_contributor_evidence(tables["evidence"]).select(KEY),
            on=KEY,
            how="anti",
            nulls_equal=True,
        )
        .join(
            tables["attempts"],
            on=KEY,
            how="left",
            validate="1:1",
            nulls_equal=True,
        )
        .sort(
            "attempted_at",
            "listing_timestamp",
            "page_id",
            descending=[False, True, False],
            nulls_last=False,
        )
        .drop("attempted_at")
    )
