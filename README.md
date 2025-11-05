# Rappi Reconciliation Project

This repository consolidates a reproducible reconciliation workflow between
Rappi's internal ledger and a third-party processor.  It delivers:

- deterministic matching between internal **disperse/debit** movements and
  the corresponding third-party **Transferencia WS / Retiro en Ventanilla WS**
  events;
- probabilistic linking of **Compra en POS** purchases to the most likely Rappi
  order using card keys and transaction timing;
- CLI entry points, reusable Python modules and notebooks for diagnostics;
- automated tests, linting and configuration-driven execution.

All executions assume the repository root as the working directory.

## Project Layout

```
.
├── config.yml                 # Default reconciliation parameters
├── Makefile                   # Common tasks (install, lint, test, run)
├── outputs/                   # Generated CSV artefacts
├── notebooks/
│   └── debug_matching.ipynb   # Data quality and matching diagnostics
├── src/
│   ├── reconciliation/
│   │   ├── __init__.py
│   │   ├── cli.py              # Typer CLI
│   │   ├── pos_linking.py      # POS linking logic
│   │   └── reconcile_transactions.py
│   └── utils/
│       ├── __init__.py
│       └── io_utils.py         # CSV/timestamp helpers
├── tests/                     # Pytest suite and synthetic fixtures
│   ├── data/
│   ├── test_io_utils.py
│   ├── test_pos_linking.py
│   └── test_reconcile_core.py
├── base_interna.csv           # Sample internal feed (optional local runs)
├── base_tercero.csv           # Sample third-party feed
└── pyproject.toml             # Packaging, linting and type checking config
```

## Installation

```bash
make install
```

This installs the project in editable mode together with the development
toolchain (pytest, ruff, mypy).

## Running the Pipelines

Execute the full reconciliation and POS linking flow using the provided
configuration:

```bash
make run
# or
python -m src.reconciliation.cli run --config config.yml
```

Additional CLI examples:

```bash
python -m src.reconciliation.cli reconcile-only --time-tolerance 1800
python -m src.reconciliation.cli pos-link-only --verbose
```

Command-line flags allow overriding the internal/third-party CSV locations,
output directory, tolerances and verbosity.  When a relative path is supplied
for the CSVs, the loader first checks `/mnt/data/` and falls back to the
current working directory.

## Outputs

Successful executions produce the following CSVs under `outputs/`:

- `matched_transactions.csv` – one-to-one matches between Rappi and the
  third-party feeds including the time difference in seconds.
- `unmatched_rappi_transactions.csv` – internal movements without a match.
- `unmatched_third_party_transactions.csv` – third-party movements without a match.
- `pos_linked_purchases.csv` – Compra en POS purchases linked to an
  `ORDER_ID_RAPPI`, including MID, amount and diagnostic metadata.

## Development Workflow

Linting and formatting checks:

```bash
make lint
```

Unit tests with coverage:

```bash
make test
```

Type checking (optional):

```bash
mypy src
```

## Configuration

Parameters are centralised in `config.yml`.  They control input paths, matching
keys, tolerances, movement filters and POS linking heuristics.  Override the
values via CLI arguments or by editing the YAML file.

## Notebook Support

`notebooks/debug_matching.ipynb` leverages the shared utilities to load the
feeds regardless of whether they reside in `/mnt/data/` or the repository root.
It also surfaces timestamp distributions, candidate time deltas and movement
crosstabs to diagnose reconciliation gaps.
