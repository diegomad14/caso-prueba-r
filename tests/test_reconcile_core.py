from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from src.reconciliation.reconcile_transactions import (
    _filter_movements,
    _merge_candidates,
    _prepare_internal_dataframe,
    _prepare_third_party_dataframe,
    _select_one_to_one_matches,
    load_config,
    reconcile_transactions,
)


def test_reconcile_transactions_happy_path(tmp_path: Path) -> None:
    cfg = load_config(Path("config.yml"))
    outputs = reconcile_transactions(
        cfg,
        internal_path=Path("tests/data/internal_basic.csv"),
        third_party_path=Path("tests/data/third_basic.csv"),
        output_dir=tmp_path,
        verbose=False,
    )

    assert len(outputs.matches) == 2
    assert set(outputs.matches["MATCH_MOVEMENT"]) == {"disperse", "debit"}
    assert outputs.unmatched_rappi.empty
    assert outputs.unmatched_third.empty

    for filename in [
        "matched_transactions.csv",
        "unmatched_rappi_transactions.csv",
        "unmatched_third_party_transactions.csv",
    ]:
        assert (tmp_path / filename).exists()


def test_reconcile_respects_time_tolerance_override(tmp_path: Path) -> None:
    cfg = load_config(Path("config.yml"))
    outputs = reconcile_transactions(
        cfg,
        internal_path=Path("tests/data/internal_basic.csv"),
        third_party_path=Path("tests/data/third_basic.csv"),
        output_dir=tmp_path,
        time_tolerance=600,
        verbose=False,
    )

    assert outputs.matches.empty
    assert len(outputs.unmatched_rappi) == 2
    assert len(outputs.unmatched_third) == 2


def test_select_one_to_one_prefers_smallest_time_diff() -> None:
    internal_raw = pd.DataFrame(
        [
            {
                "CREATED_AT_RAPPI": "2023-01-01 10:00:00",
                "FECHA_RAPPI": "2023-01-01",
                "HORA_RAPPI": "10:00:00",
                "IDENTIFICADOR_RAPPI": "id123",
                "AUTH_CODE_RAPPI": "ac001",
                "BIN_NUMBER_RAPPI": "123456",
                "FOUR_DIGITS_RAPPI": "7890",
                "MOVIMIENTO_RAPPI": "disperse",
                "VALOR_RAPPI": "100.00",
                "ORDER_ID_RAPPI": "ORDER-ABC",
            }
        ]
    )

    third_raw = pd.DataFrame(
        [
            {
                "TRANSACTION_DATETIME_TERCERO": "2023-01-01 10:03:00",
                "FECHA_TERCERO": "2023-01-01",
                "HORA_TERCERO": "10:03:00",
                "IDENTIFICADOR_TERCERO": "id123",
                "AUTH_CODE_TERCERO": "ac001",
                "BIN_TERCERO": "123456",
                "LAST_FOUR_DIGITS_TERCERO": "7890",
                "DESCRIPCION_TERCERO": "Transferencia WS",
                "MID_TERCERO": "MID-1",
                "CREDITO_TERCERO": "100.00",
                "DEBITO_TERCERO": "0.00",
            },
            {
                "TRANSACTION_DATETIME_TERCERO": "2023-01-01 10:25:00",
                "FECHA_TERCERO": "2023-01-01",
                "HORA_TERCERO": "10:25:00",
                "IDENTIFICADOR_TERCERO": "id123",
                "AUTH_CODE_TERCERO": "ac001",
                "BIN_TERCERO": "123456",
                "LAST_FOUR_DIGITS_TERCERO": "7890",
                "DESCRIPCION_TERCERO": "Transferencia WS",
                "MID_TERCERO": "MID-1",
                "CREDITO_TERCERO": "100.00",
                "DEBITO_TERCERO": "0.00",
            },
        ]
    )

    internal = _prepare_internal_dataframe(internal_raw)
    third = _prepare_third_party_dataframe(third_raw)
    join_keys = ["IDENTIFICADOR", "AUTH_CODE", "BIN", "LAST_4"]

    internal_filtered, third_filtered = _filter_movements(
        internal, third, "disperse", "Transferencia WS", join_keys
    )
    candidates = _merge_candidates(internal_filtered, third_filtered, join_keys)

    matches = _select_one_to_one_matches(
        candidates,
        time_tolerance=3600,
        amount_tolerance=0.01,
        movement_key="disperse",
    )

    assert len(matches) == 1
    assert str(matches.iloc[0]["TIMESTAMP_TERCERO"]) == "2023-01-01 10:03:00"
