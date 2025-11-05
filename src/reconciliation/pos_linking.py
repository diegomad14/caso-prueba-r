"""Link "Compra en POS" movements to Rappi disperse/debit flows."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Dict, List

import pandas as pd

from .reconcile_transactions import ReconciliationConfig

LOGGER = logging.getLogger(__name__)


def _end_of_day(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.normalize() + timedelta(days=1) - timedelta(microseconds=1)


def _select_candidate_disperse(
    disperse_rows: pd.DataFrame, pos_time: pd.Timestamp
) -> pd.Series | None:
    candidates = disperse_rows[disperse_rows["TIMESTAMP_RAPPI"] <= pos_time]
    if candidates.empty:
        return None
    return candidates.sort_values("TIMESTAMP_RAPPI").iloc[-1]


def _next_debit_time(
    debit_rows: pd.DataFrame, reference_time: pd.Timestamp
) -> pd.Timestamp | None:
    future = debit_rows[debit_rows["TIMESTAMP_RAPPI"] >= reference_time]
    if future.empty:
        return None
    return future.sort_values("TIMESTAMP_RAPPI").iloc[0]["TIMESTAMP_RAPPI"]


def _compute_window_end(
    strategy: str,
    disperse_time: pd.Timestamp,
    next_debit_time: pd.Timestamp | None,
) -> pd.Timestamp:
    if strategy == "between_disperse_and_next_debit" and next_debit_time is not None:
        return next_debit_time
    if strategy == "same_day_after_disperse":
        return disperse_time.normalize() + timedelta(days=1) - timedelta(microseconds=1)
    return _end_of_day(disperse_time)


def _is_within_window(
    strategy: str,
    disperse_time: pd.Timestamp,
    pos_time: pd.Timestamp,
    window_end: pd.Timestamp,
) -> bool:
    if strategy == "same_day_after_disperse":
        return (
            disperse_time.date() == pos_time.date()
            and disperse_time <= pos_time <= window_end
        )
    return disperse_time <= pos_time <= window_end


def link_pos_purchases(
    internal_df: pd.DataFrame,
    third_df: pd.DataFrame,
    cfg: ReconciliationConfig,
) -> pd.DataFrame:
    """Link POS purchases to the most likely Rappi order."""

    label = cfg.pos_linking.description_label.lower()
    join_keys = cfg.matching.join_keys

    pos_candidates = third_df[third_df["DESCRIPCION_KEY"] == label].copy()
    pos_candidates = pos_candidates.dropna(subset=["TIMESTAMP_TERCERO"])
    for key in join_keys:
        pos_candidates = pos_candidates[pos_candidates[key].notna()]

    if pos_candidates.empty:
        LOGGER.info("No POS purchases found for linking.")
        return pd.DataFrame()

    disperse_rows = internal_df[internal_df["MOVIMIENTO_KEY"] == "disperse"].copy()
    debit_rows = internal_df[internal_df["MOVIMIENTO_KEY"] == "debit"].copy()

    if disperse_rows.empty:
        LOGGER.warning("No disperse transactions available for POS linking.")
        return pd.DataFrame()

    results: List[Dict[str, object]] = []

    grouped_disperse = disperse_rows.groupby(join_keys, dropna=False)
    grouped_debit = debit_rows.groupby(join_keys, dropna=False)
    grouped_pos = pos_candidates.groupby(join_keys, dropna=False)

    for card_key, card_pos in grouped_pos:
        if card_key not in grouped_disperse.groups:
            continue
        disperse_group = grouped_disperse.get_group(card_key).sort_values("TIMESTAMP_RAPPI")
        debit_group = (
            grouped_debit.get_group(card_key).sort_values("TIMESTAMP_RAPPI")
            if card_key in grouped_debit.groups
            else pd.DataFrame(columns=disperse_group.columns)
        )

        for _, pos_row in card_pos.sort_values("TIMESTAMP_TERCERO").iterrows():
            pos_time = pos_row["TIMESTAMP_TERCERO"]
            disperse_match = _select_candidate_disperse(disperse_group, pos_time)
            if disperse_match is None:
                continue
            next_debit = _next_debit_time(debit_group, disperse_match["TIMESTAMP_RAPPI"])
            window_end = _compute_window_end(
                cfg.pos_linking.window_strategy,
                disperse_match["TIMESTAMP_RAPPI"],
                next_debit,
            )
            if not _is_within_window(
                cfg.pos_linking.window_strategy,
                disperse_match["TIMESTAMP_RAPPI"],
                pos_time,
                window_end,
            ):
                continue

            diff_seconds = (pos_time - disperse_match["TIMESTAMP_RAPPI"]).total_seconds()
            results.append(
                {
                    "ORDER_ID_RAPPI": disperse_match.get("ORDER_ID_RAPPI"),
                    "TRANSACTION_TIME_POS": pos_time,
                    "MID_TERCERO": pos_row.get("MID_TERCERO"),
                    "DEBITO_TERCERO": pos_row.get("DEBITO_TERCERO"),
                    "MATCH_SOURCE": cfg.pos_linking.window_strategy,
                    "POS_TIME_DIFF_SECONDS": diff_seconds,
                    "IDENTIFICADOR": disperse_match.get("IDENTIFICADOR"),
                    "AUTH_CODE": disperse_match.get("AUTH_CODE"),
                    "BIN": disperse_match.get("BIN"),
                    "LAST_4": disperse_match.get("LAST_4"),
                }
            )

    if not results:
        LOGGER.info("POS linking completed with no matches.")
        return pd.DataFrame()

    linked_df = pd.DataFrame(results)
    linked_df.sort_values(by=["POS_TIME_DIFF_SECONDS", "ORDER_ID_RAPPI"], inplace=True)
    return linked_df
