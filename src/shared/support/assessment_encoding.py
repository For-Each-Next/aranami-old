"""Encode and restore stored assessments and task-force memberships."""

from __future__ import annotations

from ast import literal_eval
from collections.abc import Mapping
from typing import TYPE_CHECKING

import polars as pl

from shared.assessment_profiles import OBSERVED_PROFILE
from shared.config import PROJECT_DATA_TASKFORCE_FLAGS

if TYPE_CHECKING:
    from shared.assessment_profiles import AssessmentProfile

TASKFORCE_LIST_COLUMNS = ("pa_taskforces", "taskforces")
TASKFORCE_FLAG_COLUMNS = tuple(PROJECT_DATA_TASKFORCE_FLAGS.values())
_TASKFORCE_LIST = pl.List(pl.String)
_INVALID_FLAGS = "Invalid saved task-force membership flags."


def _taskforce_members() -> pl.Expr:
    """Reconstruct sorted memberships and null observations.

    Returns:
        A list expression over the six saved Boolean columns.
    """
    members = pl.concat_list([
        pl.when(pl.col(flag)).then(pl.lit(name))
        for name, flag in sorted(PROJECT_DATA_TASKFORCE_FLAGS.items())
    ]).list.drop_nulls()
    return pl.when(pl.col(TASKFORCE_FLAG_COLUMNS[0]).is_not_null()).then(
        members,
    )


def encode_taskforce_flags(
    frame: pl.DataFrame,
) -> tuple[pl.DataFrame, dict[str, str]]:
    """Replace canonical membership lists with nullable Boolean fields.

    Returns:
        Physical rows and the original list types. Noncanonical lists
        retain their original representation so no information is lost.
    """
    types = {
        name: dtype
        for name, dtype in frame.schema.items()
        if name in TASKFORCE_LIST_COLUMNS
        and isinstance(dtype, pl.List)
        and (dtype.inner == pl.String or isinstance(dtype.inner, pl.Enum))
    }
    if not types or set(TASKFORCE_FLAG_COLUMNS).intersection(frame.columns):
        return frame, {}
    source = next(iter(types))
    members = pl.col(source).cast(_TASKFORCE_LIST)
    flags = frame.select(
        members.list.contains(name).alias(flag)
        for name, flag in PROJECT_DATA_TASKFORCE_FLAGS.items()
    )
    restored = flags.select(_taskforce_members()).to_series()
    if any(
        not frame[name].cast(_TASKFORCE_LIST).equals(restored)
        for name in types
    ):
        return frame, {}
    names = frame.columns
    index = names.index(source)
    names[index:index] = TASKFORCE_FLAG_COLUMNS
    return (
        frame.hstack(flags).select(
            name for name in names if name not in types
        ),
        {name: str(dtype) for name, dtype in types.items()},
    )


def restore_taskforce_flags(
    frame: pl.DataFrame,
    columns: list[str],
    types: dict[str, str],
) -> pl.DataFrame:
    """Restore the saved membership list types and column positions.

    Returns:
        Logical rows with the original membership observations.

    Raises:
        ValueError: Saved flags disagree with their descriptor.
    """
    flags = TASKFORCE_FLAG_COLUMNS
    schema = frame.schema
    if (
        not types
        or not types.keys() <= set(TASKFORCE_LIST_COLUMNS)
        or types.keys() & schema.keys()
        or any(schema.get(flag) != pl.Boolean for flag in flags)
    ):
        raise ValueError(_INVALID_FLAGS)
    logical_names = (schema.keys() - set(flags)) | types.keys()
    if len(columns) != len(logical_names) or set(columns) != logical_names:
        raise ValueError(_INVALID_FLAGS)
    null_mismatch = pl.any_horizontal(
        pl.col(flag).is_null() != pl.col(flags[0]).is_null()
        for flag in flags[1:]
    )
    if frame.select(null_mismatch.any()).item():
        raise ValueError(_INVALID_FLAGS)
    members = _taskforce_members()
    restored = []
    for name, dtype in types.items():
        if dtype == str(_TASKFORCE_LIST):
            restored.append(members.alias(name))
        elif dtype.startswith("List(Enum(categories=") and dtype.endswith(
            "))",
        ):
            enum = _saved_enum(dtype[5:-1])
            restored.append(members.cast(pl.List(enum)).alias(name))
        else:
            raise ValueError(_INVALID_FLAGS)
    return frame.with_columns(restored).select(columns)


def _categories(
    name: str,
    profile: AssessmentProfile = OBSERVED_PROFILE,
) -> tuple[str, ...] | None:
    """Select the vocabulary for an assessment column.

    Args:
        name: Column name to classify.
        profile: Raw source vocabulary for one wiki/project scope.

    Returns:
        Standard labels, or None for unrelated columns.
    """
    if name == "class" or name.endswith("_class"):
        return profile.class_values
    if name == "importance" or name.endswith("_importance"):
        return profile.importance_values
    return None


def encode_assessments(
    frame: pl.DataFrame,
    *,
    profile: AssessmentProfile = OBSERVED_PROFILE,
) -> pl.DataFrame:
    """Encode assessment strings without changing source values.

    Args:
        frame: Eager table with optional assessment columns.
        profile: Explicit wiki/project raw vocabulary. Derived or
            unscoped tables retain only their observed labels; they
            do not inherit a combined multilingual declaration.

    Returns:
        A table whose assessment strings use Enum declarations with
        declared labels followed by sorted observed extra labels.
        Nulls remain null and other columns are unchanged.
    """
    expressions = []
    for name, dtype in frame.schema.items():
        categories = _categories(name, profile)
        if dtype != pl.String or categories is None:
            continue
        declared = frame.select(
            pl
            .lit(pl.Series(categories, dtype=pl.String))
            .append(pl.col(name).drop_nulls().unique().sort())
            .unique(maintain_order=True),
        ).to_series()
        expressions.append(pl.col(name).cast(pl.Enum(declared)))
    return frame.with_columns(expressions)


def decode_assessments(frame: pl.DataFrame) -> pl.DataFrame:
    """Restore assessment enums to the String API contract.

    Args:
        frame: Eager table loaded from storage or supplied by a caller.

    Returns:
        A table with assessment enums cast to String. Other columns and
        types, including unrelated enums and existing strings, survive.
    """
    return frame.with_columns(
        pl.col(name).cast(pl.String)
        for name, dtype in frame.schema.items()
        if isinstance(dtype, pl.Enum) and _categories(name) is not None
    )


def restore_assessment_schema(
    frame: pl.DataFrame,
    declared_columns: Mapping[str, str],
) -> pl.DataFrame:
    """Restore saved assessment Enums after a Parquet String read.

    Polars 2 reads Parquet Enum columns as String. Retained canonical
    column declarations restore their exact original vocabularies,
    independently of current profile configuration. Callers must bound
    manifest input and compare the complete schema after restoration.

    Args:
        frame: Loaded table with original raw observations.
        declared_columns: Saved column-to-type declarations.

    Returns:
        Table with declared assessment Enums restored. Other columns,
        raw unknown values, and null observations are unchanged.

    Raises:
        ValueError: An Enum declaration is malformed or excludes an
            observed value.
    """
    if not isinstance(declared_columns, Mapping):
        message = "Stored assessment columns require a schema mapping."
        raise ValueError(message)  # ruff: ignore[type-check-without-type-error]
    expressions = []
    for name, dtype in frame.schema.items():
        declared = declared_columns.get(name)
        if (
            name == "pa_taskforces"
            and isinstance(declared, str)
            and declared.startswith("List(Enum(categories=")
        ):
            expressions.append(
                pl.col(name).cast(pl.List(_saved_enum(declared[5:-1]))),
            )
            continue
        if (
            dtype != pl.String
            or not isinstance(declared, str)
            or not declared.startswith("Enum(categories=")
        ):
            continue
        expressions.append(pl.col(name).cast(_saved_enum(declared)))
    try:
        return frame.with_columns(expressions)
    except pl.exceptions.PolarsError:
        message = "Stored assessments disagree with their Enum declaration."
        raise ValueError(message) from None


def _saved_enum(declared: str) -> pl.Enum:
    """Validate a canonical saved Enum type without evaluating code.

    Returns:
        Exact original assessment vocabulary, including unknown extras.

    Raises:
        ValueError: The declaration is malformed or noncanonical.
    """
    message = "Stored assessments disagree with their Enum declaration."
    try:
        categories = literal_eval(declared[len("Enum(categories=") : -1])
    except ValueError, TypeError, SyntaxError, RecursionError:
        raise ValueError(message) from None
    if not isinstance(categories, list) or not all(
        isinstance(value, str) for value in categories
    ):
        raise ValueError(message)
    try:
        restored = pl.Enum(categories)
    except pl.exceptions.PolarsError:
        raise ValueError(message) from None
    if str(restored) != declared:
        raise ValueError(message)
    return restored
