from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from src.reconciliation import ReconciliationConfig
from src.reconciliation.pos_linking import link_pos_purchases
from src.reconciliation.reconcile_transactions import (
    _prepare_internal_dataframe,
    _prepare_third_party_dataframe,
    load_config,
    load_datasets,
)


def _load_prepared_frames() -> tuple[pd.DataFrame, pd.DataFrame, ReconciliationConfig]:
    cfg = load_config(Path("config.yml"))
    internal_df, third_df = load_datasets(
        cfg,
        internal_path=Path("tests/data/internal_basic.csv"),
        third_party_path=Path("tests/data/third_basic.csv"),
    )
    return internal_df, third_df, cfg


def test_link_pos_purchases_within_window() -> None:
    internal_df, third_df, cfg = _load_prepared_frames()
    linked = link_pos_purchases(internal_df, third_df, cfg)

    assert len(linked) == 1
    row = linked.iloc[0]
    assert row["ORDER_ID_RAPPI"] == "ORDER-1"
    assert row["MATCH_SOURCE"] == cfg.pos_linking.window_strategy
    assert row["POS_TIME_DIFF_SECONDS"] >= 0


def test_link_pos_purchases_outside_window() -> None:
    internal_df, third_df, cfg = _load_prepared_frames()
    adjusted_third = third_df.copy()
    mask = adjusted_third["DESCRIPCION_KEY"] == cfg.pos_linking.description_label.lower()
    adjusted_third.loc[mask, "TIMESTAMP_TERCERO"] = adjusted_third.loc[
        mask, "TIMESTAMP_TERCERO"
    ] + pd.Timedelta(hours=3)

    linked = link_pos_purchases(internal_df, adjusted_third, cfg)
    assert linked.empty


def test_link_pos_purchases_prefers_latest_disperse() -> None:
    cfg = load_config(Path("config.yml"))

    internal_raw = pd.DataFrame(
        [
            {
                "CREATED_AT_RAPPI": "2023-01-01 09:00:00",
                "FECHA_RAPPI": "2023-01-01",
                "HORA_RAPPI": "09:00:00",
                "IDENTIFICADOR_RAPPI": "id999",
                "AUTH_CODE_RAPPI": "auth1",
                "BIN_NUMBER_RAPPI": "654321",
                "FOUR_DIGITS_RAPPI": "1111",
                "MOVIMIENTO_RAPPI": "disperse",
                "VALOR_RAPPI": "50.00",
                "ORDER_ID_RAPPI": "ORDER-OLD",
            },
            {
                "CREATED_AT_RAPPI": "2023-01-01 10:00:00",
                "FECHA_RAPPI": "2023-01-01",
                "HORA_RAPPI": "10:00:00",
                "IDENTIFICADOR_RAPPI": "id999",
                "AUTH_CODE_RAPPI": "auth2",
                "BIN_NUMBER_RAPPI": "654321",
                "FOUR_DIGITS_RAPPI": "1111",
                "MOVIMIENTO_RAPPI": "disperse",
                "VALOR_RAPPI": "60.00",
                "ORDER_ID_RAPPI": "ORDER-NEW",
            },
            {
                "CREATED_AT_RAPPI": "2023-01-01 12:00:00",
                "FECHA_RAPPI": "2023-01-01",
                "HORA_RAPPI": "12:00:00",
                "IDENTIFICADOR_RAPPI": "id999",
                "AUTH_CODE_RAPPI": "auth3",
                "BIN_NUMBER_RAPPI": "654321",
                "FOUR_DIGITS_RAPPI": "1111",
                "MOVIMIENTO_RAPPI": "debit",
                "VALOR_RAPPI": "60.00",
                "ORDER_ID_RAPPI": "ORDER-NEW",
            },
        ]
    )

    third_raw = pd.DataFrame(
        [
            {
                "TRANSACTION_DATETIME_TERCERO": "2023-01-01 10:30:00",
                "FECHA_TERCERO": "2023-01-01",
                "HORA_TERCERO": "10:30:00",
                "IDENTIFICADOR_TERCERO": "id999",
                "AUTH_CODE_TERCERO": "pos999",
                "BIN_TERCERO": "654321",
                "LAST_FOUR_DIGITS_TERCERO": "1111",
                "DESCRIPCION_TERCERO": "Compra en POS",
                "MID_TERCERO": "MID-9",
                "CREDITO_TERCERO": "0.00",
                "DEBITO_TERCERO": "55.00",
            }
        ]
    )

    internal_df = _prepare_internal_dataframe(internal_raw)
    third_df = _prepare_third_party_dataframe(third_raw)
    linked = link_pos_purchases(internal_df, third_df, cfg)

    assert len(linked) == 1
    assert linked.iloc[0]["ORDER_ID_RAPPI"] == "ORDER-NEW"
