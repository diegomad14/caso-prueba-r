"""Typer-powered CLI to run reconciliation and POS linking pipelines."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import typer

from .pos_linking import link_pos_purchases
from .reconcile_transactions import (
    ReconciliationConfig,
    ReconciliationOutputs,
    load_config,
    load_datasets,
    reconcile_transactions,
)

app = typer.Typer(help="Rappi reconciliation workflows")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s - %(message)s")


def _load_configuration(config_path: Path) -> ReconciliationConfig:
    return load_config(config_path)


def _persist_pos_links(pos_df: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pos_df.to_csv(output_dir / "pos_linked_purchases.csv", index=False)


def _print_reconciliation_summary(outputs: ReconciliationOutputs) -> None:
    typer.echo(f"Matched transactions: {len(outputs.matches)}")
    typer.echo(f"Unmatched Rappi transactions: {len(outputs.unmatched_rappi)}")
    typer.echo(f"Unmatched third-party transactions: {len(outputs.unmatched_third)}")

    if not outputs.matches.empty:
        typer.echo("Match counts by movement:")
        counts = outputs.matches["MATCH_MOVEMENT"].value_counts().to_dict()
        for movement, count in counts.items():
            typer.echo(f"  - {movement}: {count}")


@app.command()
def run(
    config: Path = typer.Option(Path("config.yml"), "--config", help="Config file path"),
    internal: Optional[Path] = typer.Option(None, "--internal", help="Override internal CSV path"),
    third: Optional[Path] = typer.Option(None, "--third", help="Override third-party CSV path"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="Custom output directory"),
    time_tolerance: Optional[int] = typer.Option(None, "--time-tolerance", help="Time tolerance in seconds"),
    amount_tolerance: Optional[float] = typer.Option(None, "--amount-tolerance", help="Amount tolerance"),
    verbose: bool = typer.Option(False, "--verbose/--no-verbose", help="Enable debug logging"),
) -> None:
    """Run reconciliation and POS linking in sequence."""

    _configure_logging(verbose)
    cfg = _load_configuration(config)
    outputs = reconcile_transactions(
        cfg,
        internal_path=internal,
        third_party_path=third,
        output_dir=output_dir,
        time_tolerance=time_tolerance,
        amount_tolerance=amount_tolerance,
        verbose=verbose,
    )

    _print_reconciliation_summary(outputs)

    pos_df = link_pos_purchases(outputs.prepared_internal, outputs.prepared_third, cfg)
    target_dir = Path(output_dir or cfg.paths.output_dir)
    _persist_pos_links(pos_df, target_dir)
    typer.echo(f"POS links generated: {len(pos_df)} -> {target_dir / 'pos_linked_purchases.csv'}")


@app.command("reconcile-only")
def reconcile_only(
    config: Path = typer.Option(Path("config.yml"), "--config"),
    internal: Optional[Path] = typer.Option(None, "--internal"),
    third: Optional[Path] = typer.Option(None, "--third"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir"),
    time_tolerance: Optional[int] = typer.Option(None, "--time-tolerance"),
    amount_tolerance: Optional[float] = typer.Option(None, "--amount-tolerance"),
    verbose: bool = typer.Option(False, "--verbose/--no-verbose"),
) -> None:
    """Run only the core reconciliation pipeline."""

    _configure_logging(verbose)
    cfg = _load_configuration(config)
    outputs = reconcile_transactions(
        cfg,
        internal_path=internal,
        third_party_path=third,
        output_dir=output_dir,
        time_tolerance=time_tolerance,
        amount_tolerance=amount_tolerance,
        verbose=verbose,
    )
    _print_reconciliation_summary(outputs)


@app.command("pos-link-only")
def pos_link_only(
    config: Path = typer.Option(Path("config.yml"), "--config"),
    internal: Optional[Path] = typer.Option(None, "--internal"),
    third: Optional[Path] = typer.Option(None, "--third"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir"),
    verbose: bool = typer.Option(False, "--verbose/--no-verbose"),
) -> None:
    """Run only the POS linking workflow."""

    _configure_logging(verbose)
    cfg = _load_configuration(config)
    internal_df, third_df = load_datasets(cfg, internal_path=internal, third_party_path=third)
    pos_df = link_pos_purchases(internal_df, third_df, cfg)
    target_dir = Path(output_dir or cfg.paths.output_dir)
    _persist_pos_links(pos_df, target_dir)
    typer.echo(f"POS links generated: {len(pos_df)} -> {target_dir / 'pos_linked_purchases.csv'}")


if __name__ == "__main__":  # pragma: no cover
    app()
