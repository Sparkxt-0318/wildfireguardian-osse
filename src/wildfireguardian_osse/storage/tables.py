"""A minimal columnar table with deterministic CSV round-tripping.

Deliberately not pandas: a world must be readable with the standard library
alone (``docs/SCOPE.md#dependency-policy``), and a fixed, explicit float
format is what makes byte-level determinism testable.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

#: 10 significant digits: far finer than any quantity here (a minute column
#: resolves to ~1e-7 min) while still being stable across runs.
FLOAT_FORMAT = "{:.10g}"


def _format(value) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return "inf" if value > 0 else ("-inf" if value < 0 else "nan")
        return FLOAT_FORMAT.format(float(value))
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError(f"table values must not contain newlines: {text!r}")
    return text


@dataclass(frozen=True)
class Table:
    """Column-oriented table with a fixed column order."""

    columns: dict[str, np.ndarray]

    def __post_init__(self) -> None:
        lengths = {len(v) for v in self.columns.values()}
        if len(lengths) > 1:
            raise ValueError(f"ragged table: column lengths {lengths}")

    @classmethod
    def from_columns(cls, columns: Mapping[str, Iterable]) -> "Table":
        return cls(columns={k: np.asarray(list(v)) for k, v in columns.items()})

    @classmethod
    def empty(cls, names: Sequence[str]) -> "Table":
        return cls(columns={n: np.asarray([]) for n in names})

    def __len__(self) -> int:
        if not self.columns:
            return 0
        return len(next(iter(self.columns.values())))

    @property
    def names(self) -> list[str]:
        return list(self.columns)

    def rows(self):
        names = self.names
        for k in range(len(self)):
            yield {n: self.columns[n][k] for n in names}

    def select(self, mask: np.ndarray) -> "Table":
        mask = np.asarray(mask, dtype=bool)
        return Table(columns={n: v[mask] for n, v in self.columns.items()})

    def sort_by(self, *keys: str) -> "Table":
        """Stable lexicographic sort.  Determinism depends on a fixed order."""
        if len(self) == 0:
            return self
        order = np.lexsort(tuple(self.columns[k] for k in reversed(keys)))
        return Table(columns={n: v[order] for n, v in self.columns.items()})

    def to_csv(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        names = self.names
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(names)
            for k in range(len(self)):
                writer.writerow([_format(self.columns[n][k]) for n in names])


def read_table(path: str | Path) -> dict[str, np.ndarray]:
    """Read a CSV written by :meth:`Table.to_csv`.

    Columns that parse cleanly as floats become float arrays; everything else
    stays as strings.  ``inf`` round-trips, which matters for arrival times.
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return {}
        raw: list[list[str]] = [row for row in reader if row]

    # Rows are padded/truncated to the header width rather than raising: a
    # truncated or corrupt file must be *reported* by the validator, not crash
    # the tool that is trying to diagnose it.
    width = len(header)
    rows = [(row + [""] * width)[:width] for row in raw]

    out: dict[str, np.ndarray] = {}
    for idx, name in enumerate(header):
        values = [row[idx] for row in rows]
        try:
            out[name] = np.array([float(v) for v in values], dtype=float)
        except ValueError:
            out[name] = np.array(values, dtype=object)
    return out
