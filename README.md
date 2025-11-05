# Rappi Reconciliation Project

This repository contains a prototype data reconciliation tool for Rappi's prepaid card and POS transaction flows. The project provides end-to-end scripts for extracting daily CSV feeds, transforming and matching records between Rappi's internal systems and a third-party processor, computing reconciliation KPIs, and raising alerts for data quality issues.

## Project Structure

```
.
├── alerts/                 # Alert generation scripts and outputs
├── data/
│   └── raw/                # Mocked daily raw files downloaded via ETL
├── outputs/                # Derived files such as KPIs and visualizations
├── src/
│   ├── analytics/          # KPI calculations and visualization scripts
│   ├── etl/                # Extraction utilities for daily feeds
│   └── reconciliation/     # Record matching and reconciliation logic
├── notebooks/              # Optional exploratory notebooks
├── base_interna.csv        # Sample internal Rappi transaction log
├── base_tercero.csv        # Sample third-party processor log
└── README.md
```

## Getting Started

1. **Create a virtual environment (optional but recommended):**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use `.venv\\Scripts\\activate`
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   If `requirements.txt` is not yet available, manually install the required packages:
   ```bash
   pip install pandas matplotlib seaborn
   ```

3. **Run the ETL pipeline:**
   ```bash
   python src/etl/download_daily_files.py
   ```

4. **Execute the reconciliation logic:**
   ```bash
   python src/reconciliation/reconcile_transactions.py
   ```

5. **Generate analytics and alerts:**
   ```bash
   python src/analytics/compute_kpis.py
   python alerts/generate_alerts.py
   ```

All scripts assume they are executed from the project root and will read/write files under the directories shown above.

## Project Goals

- Simulate daily ingestion of transaction CSV files from an external source.
- Reconcile internal disperse/debit movements with third-party records.
- Match POS purchases to Rappi orders using card information and time proximity.
- Produce daily reconciliation KPIs and simple visualizations.
- Detect potential data quality issues such as missing files, duplicates, and unmatched records.

Further implementation details will be added as the project progresses.
