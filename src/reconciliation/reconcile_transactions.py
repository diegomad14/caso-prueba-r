"""Reconciliation utilities for matching Rappi transactions with third-party records.

This module loads the internal (Rappi) and external (third-party) CSV files and
attempts to reconcile two specific flows:

* ``disperse`` in the Rappi data with ``Transferencia WS`` in the third-party data.
* ``debit`` in the Rappi data with ``Retiro en Ventanilla WS`` in the third-party data.

Transactions are matched when they share the same identifier, authorization code,
BIN and last four digits, and when their timestamps fall within a one hour window.

Running this script from the repository root will generate three CSV files under
``outputs/``:

* ``matched_transactions.csv`` – consolidated view of the matched pairs.
* ``unmatched_rappi_transactions.csv`` – Rappi records that could not be matched.
* ``unmatched_third_party_transactions.csv`` – third-party records left unmatched.

All paths are resolved relative to the repository root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INTERNAL_PATH = REPO_ROOT / "base_interna.csv"
DEFAULT_THIRD_PARTY_PATH = REPO_ROOT / "base_tercero.csv"
OUTPUT_DIR = REPO_ROOT / "outputs"

# Required columns for matching
INTERNAL_COLUMNS = {
    "CREATED_AT_RAPPI",
    "IDENTIFICADOR_RAPPI",
    "AUTH_CODE_RAPPI",
    "BIN_NUMBER_RAPPI",
    "FOUR_DIGITS_RAPPI",
    "MOVIMIENTO_RAPPI",
    "ORDER_ID_RAPPI",
    "TRANSACTION_ID_RAPPI",
    "VALOR_RAPPI",
}

THIRD_PARTY_COLUMNS = {
    "TRANSACTION_DATETIME_TERCERO",
    "IDENTIFICADOR_TERCERO",
    "AUTH_CODE_TERCERO",
    "BIN_TERCERO",
    "LAST_FOUR_DIGITS_TERCERO",
    "DESCRIPCION_TERCERO",
    "MID_TERCERO",
    "CREDITO_TERCERO",
    "DEBITO_TERCERO",
}

MATCH_JOIN_COLUMNS = ["IDENTIFICADOR", "AUTH_CODE", "BIN", "LAST_4"]
TIME_TOLERANCE_SECONDS = 60 * 60  # +/- 1 hour


@dataclass
class MatchResult:
    """Container for match outputs."""

    matches: pd.DataFrame
    unmatched_rappi: pd.DataFrame
    unmatched_third: pd.DataFrame


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def load_internal_transactions(path: Path) -> pd.DataFrame:
    """Load and prepare the internal (Rappi) dataset."""
    df = pd.read_csv(path)
    missing = INTERNAL_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"Internal file missing columns: {sorted(missing)}")

    prepared = df.copy()
    prepared["TRANSACTION_TIME"] = pd.to_datetime(prepared["CREATED_AT_RAPPI"], errors="coerce")
    prepared["IDENTIFICADOR"] = prepared["IDENTIFICADOR_RAPPI"].astype(str).str.strip()
    prepared["AUTH_CODE"] = prepared["AUTH_CODE_RAPPI"].astype(str).str.strip()
    prepared["BIN"] = prepared["BIN_NUMBER_RAPPI"].astype(str).str.strip()
    prepared["LAST_4"] = prepared["FOUR_DIGITS_RAPPI"].astype(str).str.strip()
    prepared["VALOR_RAPPI"] = pd.to_numeric(prepared["VALOR_RAPPI"], errors="coerce")

    # Preserve a unique identifier per row for matching bookkeeping
    prepared["RAPPI_ROW_ID"] = prepared.index
    return prepared


def load_third_party_transactions(path: Path) -> pd.DataFrame:
    """Load and prepare the third-party dataset."""
    df = pd.read_csv(path)
    missing = THIRD_PARTY_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"Third-party file missing columns: {sorted(missing)}")

    prepared = df.copy()
    prepared["TRANSACTION_TIME"] = pd.to_datetime(
        prepared["TRANSACTION_DATETIME_TERCERO"], errors="coerce"
    )
    prepared["IDENTIFICADOR"] = prepared["IDENTIFICADOR_TERCERO"].astype(str).str.strip()
    prepared["AUTH_CODE"] = prepared["AUTH_CODE_TERCERO"].astype(str).str.strip()
    prepared["BIN"] = prepared["BIN_TERCERO"].astype(str).str.strip()
    prepared["LAST_4"] = prepared["LAST_FOUR_DIGITS_TERCERO"].astype(str).str.strip()
    prepared["CREDITO_TERCERO"] = pd.to_numeric(prepared["CREDITO_TERCERO"], errors="coerce")
    prepared["DEBITO_TERCERO"] = pd.to_numeric(prepared["DEBITO_TERCERO"], errors="coerce")

    prepared["THIRD_ROW_ID"] = prepared.index
    return prepared


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def match_transactions(
    rappi_df: pd.DataFrame,
    third_df: pd.DataFrame,
    movement_type: str,
    third_description: str,
) -> MatchResult:
    """Match Rappi transactions with third-party records.

    Args:
        rappi_df: Prepared internal dataframe.
        third_df: Prepared third-party dataframe.
        movement_type: Rappi ``MOVIMIENTO_RAPPI`` value to filter.
        third_description: Third-party ``DESCRIPCION_TERCERO`` to filter.

    Returns:
        ``MatchResult`` containing the matched dataframe and the unmatched
        slices of both inputs.
    """

    rappi_filtered = rappi_df[rappi_df["MOVIMIENTO_RAPPI"].str.lower() == movement_type.lower()].copy()
    third_filtered = third_df[
        third_df["DESCRIPCION_TERCERO"].str.lower() == third_description.lower()
    ].copy()

    if rappi_filtered.empty or third_filtered.empty:
        # No candidates; immediately return empty matches and full unmatched lists.
        return MatchResult(
            matches=pd.DataFrame(),
            unmatched_rappi=rappi_filtered,
            unmatched_third=third_filtered,
        )

    candidates = rappi_filtered.merge(
        third_filtered,
        on=MATCH_JOIN_COLUMNS,
        suffixes=("_RAPPI", "_TERCERO"),
        how="inner",
    )

    if candidates.empty:
        return MatchResult(
            matches=pd.DataFrame(),
            unmatched_rappi=rappi_filtered,
            unmatched_third=third_filtered,
        )

    candidates["TIME_DIFF_SECONDS"] = (
        candidates["TRANSACTION_TIME_RAPPI"] - candidates["TRANSACTION_TIME_TERCERO"]
    ).abs().dt.total_seconds()

    candidates = candidates[candidates["TIME_DIFF_SECONDS"] <= TIME_TOLERANCE_SECONDS].copy()

    if candidates.empty:
        return MatchResult(
            matches=pd.DataFrame(),
            unmatched_rappi=rappi_filtered,
            unmatched_third=third_filtered,
        )

    # Sort by the smallest time difference to prioritise closest matches.
    candidates.sort_values("TIME_DIFF_SECONDS", inplace=True)

    selected_indices: List[int] = []
    used_rappi: set = set()
    used_third: set = set()

    for idx, row in candidates.iterrows():
        rappi_id = row["RAPPI_ROW_ID"]
        third_id = row["THIRD_ROW_ID"]
        if rappi_id in used_rappi or third_id in used_third:
            continue
        selected_indices.append(idx)
        used_rappi.add(rappi_id)
        used_third.add(third_id)

    matches = candidates.loc[selected_indices].copy()

    unmatched_rappi = rappi_filtered[~rappi_filtered["RAPPI_ROW_ID"].isin(matches["RAPPI_ROW_ID"])]
    unmatched_third = third_filtered[~third_filtered["THIRD_ROW_ID"].isin(matches["THIRD_ROW_ID"])]

    return MatchResult(matches=matches, unmatched_rappi=unmatched_rappi, unmatched_third=unmatched_third)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reconcile_transactions(
    internal_path: Path = DEFAULT_INTERNAL_PATH,
    third_party_path: Path = DEFAULT_THIRD_PARTY_PATH,
    output_dir: Path = OUTPUT_DIR,
) -> Dict[str, pd.DataFrame]:
    """Execute the reconciliation pipeline and persist the outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    rappi_df = load_internal_transactions(internal_path)
    third_df = load_third_party_transactions(third_party_path)

    disperse_matches = match_transactions(rappi_df, third_df, "disperse", "Transferencia WS")
    debit_matches = match_transactions(rappi_df, third_df, "debit", "Retiro en Ventanilla WS")

    # Combine matched outputs with a flag for the movement type for downstream analysis.
    matched_frames = []
    if not disperse_matches.matches.empty:
        frame = disperse_matches.matches.copy()
        frame["MATCH_TYPE"] = "disperse-Transferencia WS"
        matched_frames.append(frame)
    if not debit_matches.matches.empty:
        frame = debit_matches.matches.copy()
        frame["MATCH_TYPE"] = "debit-Retiro en Ventanilla WS"
        matched_frames.append(frame)

    consolidated_matches = (
        pd.concat(matched_frames, ignore_index=True, sort=False)
        if matched_frames
        else pd.DataFrame()
    )

    unmatched_rappi = pd.concat(
        [disperse_matches.unmatched_rappi, debit_matches.unmatched_rappi],
        ignore_index=True,
        sort=False,
    )
    unmatched_third = pd.concat(
        [disperse_matches.unmatched_third, debit_matches.unmatched_third],
        ignore_index=True,
        sort=False,
    )

    consolidated_matches.to_csv(output_dir / "matched_transactions.csv", index=False)
    unmatched_rappi.to_csv(output_dir / "unmatched_rappi_transactions.csv", index=False)
    unmatched_third.to_csv(output_dir / "unmatched_third_party_transactions.csv", index=False)

    return {
        "matches": consolidated_matches,
        "unmatched_rappi": unmatched_rappi,
        "unmatched_third": unmatched_third,
    }


def main() -> None:
    """CLI entry point for manual executions."""
    results = reconcile_transactions()

    print("Reconciliation completed.")
    print(f"Matched transactions: {len(results['matches'])}")
    print(f"Unmatched Rappi transactions: {len(results['unmatched_rappi'])}")
    print(f"Unmatched third-party transactions: {len(results['unmatched_third'])}")


if __name__ == "__main__":
    main()
