"""Store typed report inputs in Parquet."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import fields
from typing import TYPE_CHECKING
from uuid import uuid4

import polars as pl

from data.article_changes import OldArticle
from data.assessment_lists import AssessmentList
from data.dyk import DykChanges, PreparedDyk
from data.key_articles import ReportData
from data.new_pages import DailyRecord, LineFacts, PageFacts, PreparedNewPages
from data.pageview_types import PageviewData, RankingData
from data.pexbot import PexBotReport
from data.reports import ReportResult, ReportStore

if TYPE_CHECKING:
    from pathlib import Path

_RECORDS = {
    record.__name__: record
    for record in (
        AssessmentList,
        DailyRecord,
        DykChanges,
        LineFacts,
        OldArticle,
        PageFacts,
        PageviewData,
        PexBotReport,
        PreparedDyk,
        PreparedNewPages,
        RankingData,
        ReportData,
        ReportResult,
    )
}


def _encode(value: object, tables: dict[str, pl.DataFrame]) -> object:  # ruff: ignore[too-many-return-statements] - One encoding per value type.
    """Replace values with JSON fields and Parquet references.

    Returns:
        The encoded value.

    Raises:
        TypeError: A value cannot be stored in report inputs.
    """
    match value:
        case pl.DataFrame():
            key = f"table-{len(tables)}"
            tables[key] = value
            return ["table", key]
        case dt.datetime():
            return ["datetime", value.isoformat()]
        case dt.date():
            return ["date", value.isoformat()]
        case Mapping():
            return [
                "mapping",
                [
                    [_encode(key, tables), _encode(entry, tables)]
                    for key, entry in value.items()
                ],
            ]
        case tuple() | list() | frozenset():
            return [
                type(value).__name__,
                [_encode(entry, tables) for entry in value],
            ]
        case str() | int() | float() | None:
            return value
        case _:
            name = type(value).__name__
            if _RECORDS.get(name) is not type(value):
                message = f"Unsupported report input type: {name}"
                raise TypeError(message)
            return [
                "record",
                name,
                {
                    field.name: _encode(getattr(value, field.name), tables)
                    for field in fields(value)
                },
            ]


def _decode(value: object, tables: Mapping[str, pl.DataFrame]) -> object:  # ruff: ignore[too-many-return-statements] - One decoding per value type.
    """Restore a typed value.

    Returns:
        A record, collection, table, or scalar read from the bundle.
    """
    match value:
        case ["table", key]:
            return tables[key]
        case ["datetime", text]:
            return dt.datetime.fromisoformat(text)
        case ["date", text]:
            return dt.date.fromisoformat(text)
        case ["mapping", entries]:
            return {
                _decode(key, tables): _decode(entry, tables)
                for key, entry in entries
            }
        case [("tuple" | "list" | "frozenset") as name, entries]:
            return {"tuple": tuple, "list": list, "frozenset": frozenset}[
                name
            ](_decode(entry, tables) for entry in entries)
        case ["record", name, values]:
            return _RECORDS[name](
                **{
                    key: _decode(entry, tables)
                    for key, entry in values.items()
                },
            )
        case _:
            return value


def _store(runtime: Path) -> ReportStore:
    """Open the input cache.

    Returns:
        A store retaining one complete input generation per report.
    """
    return ReportStore(
        runtime / "cache" / ".toolforge-inputs",
        keep_previous=False,
    )


def save_inputs(
    runtime: Path,
    name: str,
    cycle: dt.datetime,
    value: object,
) -> None:
    """Commit a report's fetched inputs for one UTC hour."""
    tables: dict[str, pl.DataFrame] = {}
    payload = json.dumps(_encode(value, tables), ensure_ascii=False)
    tables["inputs"] = pl.DataFrame({"payload": [payload]})
    _store(runtime).write(
        f"inputs/zhwiki/{name}",
        ReportResult(
            family="report-inputs",
            tables=tables,
            metadata={"cycle": cycle.isoformat()},
        ),
        "",
        run_id=uuid4().hex,
        started_at=dt.datetime.now(dt.UTC),
        target={"site": "zhwiki", "title": name},
    )


def load_inputs(runtime: Path, name: str, cycle: dt.datetime) -> object:
    """Read the selected report inputs.

    Returns:
        Decoded structured observations for the cycle.

    Raises:
        FileNotFoundError: No report inputs are available for the hour.
    """
    bundle = _store(runtime).read(f"inputs/zhwiki/{name}")
    if (
        bundle is None
        or bundle.manifest["metadata"]["cycle"] != cycle.isoformat()
    ):
        message = f"Missing {name} inputs for {cycle.isoformat()}."
        raise FileNotFoundError(message)
    return _decode(json.loads(bundle.tables["inputs"].item()), bundle.tables)
