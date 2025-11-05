from __future__ import annotations

import csv
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from src.utils.io_utils import build_timestamp, load_csv_with_fallback


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def test_load_csv_prefers_mnt_data(tmp_path: Path) -> None:
    file_name = "io_utils_sample.csv"
    mnt_path = Path("/mnt/data") / file_name
    cwd_path = Path.cwd() / file_name

    if cwd_path.exists():
        cwd_path.unlink()
    mnt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(
        mnt_path,
        [["col1", "col2"], ["a", "1"], ["b", "2"]],
    )

    try:
        frame = load_csv_with_fallback(file_name)
        assert list(frame.columns) == ["col1", "col2"]
        assert frame.iloc[0]["col1"] == "a"
    finally:
        if mnt_path.exists():
            mnt_path.unlink()


def test_load_csv_falls_back_to_cwd(tmp_path: Path) -> None:
    file_name = "io_utils_local.csv"
    mnt_path = Path("/mnt/data") / file_name
    if mnt_path.exists():
        mnt_path.unlink()
    local_path = Path.cwd() / file_name
    _write_csv(
        local_path,
        [["value"], ["42"]],
    )

    try:
        frame = load_csv_with_fallback(file_name)
        assert frame.iloc[0]["value"] == "42"
    finally:
        if local_path.exists():
            local_path.unlink()


def test_load_csv_missing_raises(tmp_path: Path) -> None:
    file_name = "missing_file.csv"
    with pytest.raises(FileNotFoundError):
        load_csv_with_fallback(file_name)


def test_build_timestamp_prefers_primary() -> None:
    df = pd.DataFrame({
        "primary": ["2023-01-01 10:00:00"],
        "date": ["2023-01-01"],
        "time": ["10:00:00"],
    })
    result = build_timestamp(df, "primary", "date", "time")
    assert str(result.iloc[0]) == "2023-01-01 10:00:00"


def test_build_timestamp_uses_fallback_when_primary_missing() -> None:
    df = pd.DataFrame({
        "primary": [None],
        "date": ["2023-01-02"],
        "time": ["12:30:00"],
    })
    result = build_timestamp(df, "primary", "date", "time")
    assert str(result.iloc[0]) == "2023-01-02 12:30:00"


def test_build_timestamp_returns_nat_when_components_missing() -> None:
    df = pd.DataFrame({
        "primary": [None],
        "date": ["2023-01-03"],
        "time": [None],
    })
    result = build_timestamp(df, "primary", "date", "time")
    assert pd.isna(result.iloc[0])
