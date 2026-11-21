"""Verify scalar Parquet relationships and immutable children."""

# The repository uses unittest for validation failures.
# ruff: file-ignore[pytest-unittest-raises-assertion]

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import polars as pl

from shared.support.parquet import parquet_metadata
from shared.support.parquet_tables import (
    MAX_BYTES,
    install_table,
    is_nested,
    link_table,
    open_table,
    read_table,
    remove_table,
    stage_table,
)


class TestScalarParquet(TestCase):
    """Exercise ordered and absent values in immutable tables."""

    def setUp(self) -> None:
        """Prepare nullable fields at multiple relationship depths."""
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.parent = self.root / "data.parquet"
        self.frame = pl.DataFrame(
            [
                (
                    1,
                    [None, {"names": []}, {"names": ["a", None, "a"]}],
                    ["one", "two"],
                    [None, 2],
                    {"value": None},
                ),
                (2, [], [], None, None),
                (3, None, None, [1, 2], {"value": 3}),
            ],
            schema={
                "id": pl.Int64,
                "items": pl.List(pl.Struct({"names": pl.List(pl.String)})),
                "taskforces": pl.List(pl.Enum(["one", "two"])),
                "pair": pl.Array(pl.Int64, 2),
                "status": pl.Struct({"value": pl.Int64}),
            },
            orient="row",
        )

    @staticmethod
    def read(path: Path) -> pl.DataFrame:
        """Read logical rows through the pinned table reader.

        Returns:
            Original rows with the relationships reconstructed.
        """
        with open_table(path, MAX_BYTES) as stream:
            return read_table(path, stream)[0]

    def publish(self, frame: pl.DataFrame) -> None:
        """Install a staged physical generation of the given rows."""
        with stage_table(
            self.parent,
            frame,
            parquet_metadata(frame, contract="test"),
        ) as staged:
            install_table(staged, self.parent)

    def test_scalar_files_preserve_nested_observations(self) -> None:
        """Keep exact types, order, empty lists, and null structs."""
        self.publish(self.frame)
        assert self.read(self.parent).equals(self.frame)
        assert self.read(self.parent).schema == self.frame.schema
        for path in self.root.rglob("*.parquet"):
            assert not any(
                is_nested(dtype)
                for dtype in pl.read_parquet_schema(path).values()
            )
        (items,) = self.root.glob("parquet-children/*/*-items.parquet")
        assert pl.read_parquet(items)["__position"].to_list() == [0, 1, 2]

    def test_linked_baseline_survives_replacement(self) -> None:
        """Keep a complete independent child set for a retained copy."""
        self.publish(self.frame)
        baseline = self.root / "baseline.parquet"
        link_table(self.parent, baseline)
        self.publish(self.frame.head(1))
        remove_table(self.parent)
        assert self.read(baseline).equals(self.frame)

    def test_modified_child_fails_closed(self) -> None:
        """Reject a different table with the same child filename."""
        self.publish(self.frame)
        (items,) = self.root.glob("parquet-children/*/*-items.parquet")
        child = pl.read_parquet(items)
        child.write_parquet(items)
        with self.assertRaises(ValueError):
            self.read(self.parent)
