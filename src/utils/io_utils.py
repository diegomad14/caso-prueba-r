"""Reusable helpers for loading source CSVs and harmonising timestamps."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


def load_csv_with_fallback(filename: str) -> pd.DataFrame:
    """Load a CSV from ``/mnt/data`` with a repo-root fallback.

    The function preserves the original formatting of every column by using
    ``dtype=str`` and raises a :class:`FileNotFoundError` when the file cannot be
    located in either location.
    """

    search_paths: Iterable[Path] = (Path("/mnt/data") / filename, Path.cwd() / filename)

    checked_paths: list[str] = []
    for candidate in search_paths:
        checked_paths.append(str(candidate))
        if candidate.exists():
            return pd.read_csv(candidate, dtype=str)

    raise FileNotFoundError(
        f"{filename} not found in {checked_paths}. Ensure the file is available in /mnt/data or the working directory."
    )


def build_timestamp(
    df: pd.DataFrame,
    primary_col: str,
    date_col: str | None,
    time_col: str | None,
) -> pd.Series:
    """Construct a timestamp from primary and split date/time columns.

    ``primary_col`` is parsed first. When either ``date_col`` or ``time_col`` is
    missing, the fallback defaults to :class:`pandas.NaT`. If both are present,
    they are combined and coerced with ``errors='coerce'`` so that malformed
    rows do not interrupt execution.
    """

    if primary_col and df.get(primary_col) is not None:
        primary_ts = pd.to_datetime(df.get(primary_col), errors="coerce")
    else:
        primary_ts = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")

    fallback_ts = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")

    date_series = df.get(date_col) if date_col else None
    time_series = df.get(time_col) if time_col else None

    if date_series is not None and time_series is not None:
        date_str = date_series.fillna("").astype(str).str.strip()
        time_str = time_series.fillna("").astype(str).str.strip()
        both_present = date_str.ne("") & time_str.ne("")
        combined = (date_str + " " + time_str).str.strip()
        combined = combined.where(both_present, None)
        fallback_ts = pd.to_datetime(combined, errors="coerce")

    return primary_ts.fillna(fallback_ts)

