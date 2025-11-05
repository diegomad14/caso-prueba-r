"""Core reconciliation pipeline for Rappi vs. third-party transactions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import yaml

from src.utils import build_timestamp, load_csv_with_fallback

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PathsConfig:
    """Path parameters declared in ``config.yml``."""

    internal_csv: str
    third_party_csv: str
    output_dir: str


@dataclass
class MatchingConfig:
    """Matching parameters controlling tolerances and join keys."""

    time_tolerance_seconds: int
    amount_tolerance: float
    join_keys: List[str]


@dataclass
class FiltersConfig:
    """Movements and descriptions used to filter the datasets."""

    internal_movements: List[str]
    third_party_map: Dict[str, str]


@dataclass
class POSLinkingConfig:
    """Configuration for the POS linking strategy."""

    description_label: str
    window_strategy: str
    tiebreaker: str


@dataclass
class ReconciliationConfig:
    """Aggregate configuration structure used across the project."""

    paths: PathsConfig
    matching: MatchingConfig
    filters: FiltersConfig
    pos_linking: POSLinkingConfig


@dataclass
class ReconciliationOutputs:
    """Results returned by :func:`reconcile_transactions`."""

    matches: pd.DataFrame
    unmatched_rappi: pd.DataFrame
    unmatched_third: pd.DataFrame
    prepared_internal: pd.DataFrame
    prepared_third: pd.DataFrame


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def load_config(config_path: Path) -> ReconciliationConfig:
    """Load ``config.yml`` and cast it into :class:`ReconciliationConfig`.

    Args:
        config_path: Path to the YAML configuration file.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        KeyError: When required sections are missing.

    Returns:
        Fully populated :class:`ReconciliationConfig` instance.
    """

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as stream:
        raw_cfg = yaml.safe_load(stream)

    paths = raw_cfg.get("paths") or {}
    matching = raw_cfg.get("matching") or {}
    filters = raw_cfg.get("filters") or {}
    pos_linking = raw_cfg.get("pos_linking") or {}

    return ReconciliationConfig(
        paths=PathsConfig(**paths),
        matching=MatchingConfig(**matching),
        filters=FiltersConfig(**filters),
        pos_linking=POSLinkingConfig(**pos_linking),
    )


# ---------------------------------------------------------------------------
# Data preparation helpers
# ---------------------------------------------------------------------------


REQUIRED_INTERNAL_COLUMNS = {
    "IDENTIFICADOR_RAPPI",
    "AUTH_CODE_RAPPI",
    "BIN_NUMBER_RAPPI",
    "FOUR_DIGITS_RAPPI",
    "MOVIMIENTO_RAPPI",
    "VALOR_RAPPI",
    "ORDER_ID_RAPPI",
}

REQUIRED_THIRD_COLUMNS = {
    "IDENTIFICADOR_TERCERO",
    "AUTH_CODE_TERCERO",
    "BIN_TERCERO",
    "LAST_FOUR_DIGITS_TERCERO",
    "DESCRIPCION_TERCERO",
    "MID_TERCERO",
    "CREDITO_TERCERO",
    "DEBITO_TERCERO",
}


def _normalise_series(values: pd.Series, *, width: int | None = None) -> pd.Series:
    """Return a normalised string series with padding and uppercase."""

    normalised = values.fillna("").astype(str).str.strip().str.upper()
    if width is not None:
        normalised = normalised.str.zfill(width)
    normalised = normalised.replace("", pd.NA)
    return normalised


def _validate_columns(df: pd.DataFrame, required: Iterable[str], dataset_name: str) -> None:
    missing = set(required).difference(df.columns)
    if missing:
        raise ValueError(f"{dataset_name} is missing required columns: {sorted(missing)}")


def _prepare_internal_dataframe(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalise the internal dataset and compute helper columns."""

    _validate_columns(raw, REQUIRED_INTERNAL_COLUMNS, "Internal dataset")

    prepared = raw.copy()
    prepared["TIMESTAMP_RAPPI"] = build_timestamp(
        prepared,
        primary_col="CREATED_AT_RAPPI",
        date_col="FECHA_RAPPI",
        time_col="HORA_RAPPI",
    )
    prepared["IDENTIFICADOR"] = _normalise_series(prepared["IDENTIFICADOR_RAPPI"])
    prepared["AUTH_CODE"] = _normalise_series(prepared["AUTH_CODE_RAPPI"])
    prepared["BIN"] = _normalise_series(prepared["BIN_NUMBER_RAPPI"], width=6)
    prepared["LAST_4"] = _normalise_series(prepared["FOUR_DIGITS_RAPPI"], width=4)
    prepared["VALOR_RAPPI"] = pd.to_numeric(prepared["VALOR_RAPPI"], errors="coerce")
    prepared["MOVIMIENTO_KEY"] = prepared["MOVIMIENTO_RAPPI"].fillna("").astype(str).str.strip().str.lower()
    prepared["ROW_ID"] = prepared.index
    return prepared


def _prepare_third_party_dataframe(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalise the third-party dataset and compute helper columns."""

    _validate_columns(raw, REQUIRED_THIRD_COLUMNS, "Third-party dataset")

    prepared = raw.copy()
    prepared["TIMESTAMP_TERCERO"] = build_timestamp(
        prepared,
        primary_col="TRANSACTION_DATETIME_TERCERO",
        date_col="FECHA_TERCERO",
        time_col="HORA_TERCERO",
    )
    prepared["IDENTIFICADOR"] = _normalise_series(prepared["IDENTIFICADOR_TERCERO"])
    prepared["AUTH_CODE"] = _normalise_series(prepared["AUTH_CODE_TERCERO"])
    prepared["BIN"] = _normalise_series(prepared["BIN_TERCERO"], width=6)
    prepared["LAST_4"] = _normalise_series(prepared["LAST_FOUR_DIGITS_TERCERO"], width=4)
    prepared["CREDITO_TERCERO"] = pd.to_numeric(prepared["CREDITO_TERCERO"], errors="coerce")
    prepared["DEBITO_TERCERO"] = pd.to_numeric(prepared["DEBITO_TERCERO"], errors="coerce")
    prepared["DESCRIPCION_KEY"] = prepared["DESCRIPCION_TERCERO"].fillna("").astype(str).str.strip().str.lower()
    prepared["ROW_ID"] = prepared.index
    return prepared


def _drop_invalid_candidates(df: pd.DataFrame, *, join_keys: Iterable[str], timestamp_col: str) -> pd.DataFrame:
    """Remove rows with incomplete join keys or timestamps."""

    filtered = df.copy()
    filtered = filtered.dropna(subset=[timestamp_col])
    for key in join_keys:
        filtered = filtered[filtered[key].notna()]
    return filtered


def load_datasets(
    cfg: ReconciliationConfig,
    *,
    internal_path: Path | None = None,
    third_party_path: Path | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load datasets using configured paths with optional overrides."""

    internal_source = internal_path or Path(cfg.paths.internal_csv)
    third_source = third_party_path or Path(cfg.paths.third_party_csv)

    if internal_path is None and not internal_source.exists():
        internal_raw = load_csv_with_fallback(internal_source.name)
    else:
        if not internal_source.exists():
            raise FileNotFoundError(f"Internal CSV not found at {internal_source}")
        internal_raw = pd.read_csv(internal_source, dtype=str)

    if third_party_path is None and not third_source.exists():
        third_raw = load_csv_with_fallback(third_source.name)
    else:
        if not third_source.exists():
            raise FileNotFoundError(f"Third-party CSV not found at {third_source}")
        third_raw = pd.read_csv(third_source, dtype=str)

    internal_prepared = _prepare_internal_dataframe(internal_raw)
    third_prepared = _prepare_third_party_dataframe(third_raw)
    return internal_prepared, third_prepared


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------


def _resolve_amount_column(movement_key: str) -> str:
    return "CREDITO_TERCERO" if movement_key == "disperse" else "DEBITO_TERCERO"


def _filter_movements(
    internal_df: pd.DataFrame,
    third_df: pd.DataFrame,
    movement_key: str,
    third_description: str,
    join_keys: Iterable[str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    internal_filtered = internal_df[internal_df["MOVIMIENTO_KEY"] == movement_key].copy()
    third_filtered = third_df[third_df["DESCRIPCION_KEY"] == third_description.lower()].copy()

    internal_filtered = _drop_invalid_candidates(
        internal_filtered, join_keys=join_keys, timestamp_col="TIMESTAMP_RAPPI"
    )
    third_filtered = _drop_invalid_candidates(
        third_filtered, join_keys=join_keys, timestamp_col="TIMESTAMP_TERCERO"
    )

    LOGGER.debug(
        "Movement '%s' candidates: %s internal / %s third-party",
        movement_key,
        len(internal_filtered),
        len(third_filtered),
    )
    return internal_filtered, third_filtered


def _select_one_to_one_matches(
    candidates: pd.DataFrame,
    *,
    time_tolerance: int,
    amount_tolerance: float,
    movement_key: str,
) -> pd.DataFrame:
    if candidates.empty:
        return candidates

    candidates = candidates.copy()
    candidates["TIME_DIFF_SECONDS"] = (
        candidates["TIMESTAMP_RAPPI"] - candidates["TIMESTAMP_TERCERO"]
    ).abs().dt.total_seconds()
    candidates = candidates[candidates["TIME_DIFF_SECONDS"] <= time_tolerance]

    amount_col = _resolve_amount_column(movement_key)
    if amount_col in candidates.columns:
        if "VALOR_RAPPI" in candidates.columns:
            amount_mask = (
                candidates[["VALOR_RAPPI", amount_col]].notna().all(axis=1)
                & (
                    (candidates["VALOR_RAPPI"] - candidates[amount_col])
                    .abs()
                    .le(amount_tolerance)
                )
            )
            # Keep rows where amounts are close enough or where one of the sides is NaN
            na_mask = candidates[["VALOR_RAPPI", amount_col]].isna().any(axis=1)
            candidates = candidates[amount_mask | na_mask]

    if candidates.empty:
        return candidates

    candidates.sort_values(
        by=["TIME_DIFF_SECONDS", "ROW_ID_x", "ROW_ID_y"], inplace=True
    )

    used_internal: set[int] = set()
    used_third: set[int] = set()
    selected_indices: List[int] = []

    for idx, row in candidates.iterrows():
        internal_id = int(row["ROW_ID_x"])
        third_id = int(row["ROW_ID_y"])
        if internal_id in used_internal or third_id in used_third:
            continue
        selected_indices.append(idx)
        used_internal.add(internal_id)
        used_third.add(third_id)

    return candidates.loc[selected_indices]


def _merge_candidates(
    internal_filtered: pd.DataFrame,
    third_filtered: pd.DataFrame,
    join_keys: Iterable[str],
) -> pd.DataFrame:
    return internal_filtered.merge(
        third_filtered,
        on=list(join_keys),
        how="inner",
        suffixes=("_RAPPI", "_TERCERO"),
    )


def _compile_outputs(
    movement_key: str,
    match_df: pd.DataFrame,
    internal_filtered: pd.DataFrame,
    third_filtered: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    match_df = match_df.copy()
    match_df["MATCH_MOVEMENT"] = movement_key

    matched_internal_ids = match_df["ROW_ID_x"].unique().tolist()
    matched_third_ids = match_df["ROW_ID_y"].unique().tolist()

    unmatched_internal = internal_filtered[~internal_filtered["ROW_ID"].isin(matched_internal_ids)]
    unmatched_third = third_filtered[~third_filtered["ROW_ID"].isin(matched_third_ids)]

    return match_df, unmatched_internal, unmatched_third


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reconcile_transactions(
    config: ReconciliationConfig | Path | str = Path("config.yml"),
    *,
    internal_path: Path | None = None,
    third_party_path: Path | None = None,
    output_dir: Path | None = None,
    time_tolerance: int | None = None,
    amount_tolerance: float | None = None,
    verbose: bool = False,
) -> ReconciliationOutputs:
    """Run the reconciliation pipeline and persist CSV outputs."""

    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)

    cfg = load_config(Path(config)) if not isinstance(config, ReconciliationConfig) else config

    internal_df, third_df = load_datasets(
        cfg,
        internal_path=internal_path,
        third_party_path=third_party_path,
    )

    tolerance_seconds = time_tolerance or cfg.matching.time_tolerance_seconds
    amount_tol = amount_tolerance if amount_tolerance is not None else cfg.matching.amount_tolerance
    join_keys = cfg.matching.join_keys

    movement_matches: List[pd.DataFrame] = []
    unmatched_internal_frames: List[pd.DataFrame] = []
    unmatched_third_frames: List[pd.DataFrame] = []

    for movement in cfg.filters.internal_movements:
        mapped_description = cfg.filters.third_party_map.get(movement)
        if not mapped_description:
            LOGGER.warning("No third-party description configured for '%s'", movement)
            continue

        internal_filtered, third_filtered = _filter_movements(
            internal_df, third_df, movement, mapped_description, join_keys
        )

        if internal_filtered.empty or third_filtered.empty:
            unmatched_internal_frames.append(internal_filtered)
            unmatched_third_frames.append(third_filtered)
            continue

        candidates = _merge_candidates(internal_filtered, third_filtered, join_keys)
        if candidates.empty:
            unmatched_internal_frames.append(internal_filtered)
            unmatched_third_frames.append(third_filtered)
            continue

        matches = _select_one_to_one_matches(
            candidates,
            time_tolerance=tolerance_seconds,
            amount_tolerance=amount_tol,
            movement_key=movement,
        )

        movement_match_df, unmatched_internal, unmatched_third = _compile_outputs(
            movement,
            matches,
            internal_filtered,
            third_filtered,
        )
        movement_matches.append(movement_match_df)
        unmatched_internal_frames.append(unmatched_internal)
        unmatched_third_frames.append(unmatched_third)

        LOGGER.info(
            "Movement '%s': %s matches, %s unmatched internal, %s unmatched third-party",
            movement,
            len(movement_match_df),
            len(unmatched_internal),
            len(unmatched_third),
        )

    consolidated_matches = (
        pd.concat(movement_matches, ignore_index=True, sort=False) if movement_matches else pd.DataFrame()
    )
    unmatched_internal_total = (
        pd.concat(unmatched_internal_frames, ignore_index=True, sort=False)
        if unmatched_internal_frames
        else pd.DataFrame()
    )
    unmatched_third_total = (
        pd.concat(unmatched_third_frames, ignore_index=True, sort=False)
        if unmatched_third_frames
        else pd.DataFrame()
    )

    out_dir = Path(output_dir or cfg.paths.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    consolidated_matches.to_csv(out_dir / "matched_transactions.csv", index=False)
    unmatched_internal_total.to_csv(out_dir / "unmatched_rappi_transactions.csv", index=False)
    unmatched_third_total.to_csv(out_dir / "unmatched_third_party_transactions.csv", index=False)

    return ReconciliationOutputs(
        matches=consolidated_matches,
        unmatched_rappi=unmatched_internal_total,
        unmatched_third=unmatched_third_total,
        prepared_internal=internal_df,
        prepared_third=third_df,
    )


