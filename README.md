# TruthTrail — Retail Intelligence & Anomaly Investigation

TruthTrail is a Python, SQL, and Streamlit analytics project that investigates unusual activity in retail transaction data. Rather than treating every unusual day as an error, it compares gross positive sales with signed transaction-line value and presents transaction-level evidence for human review.

> **Important:** A flagged anomaly is a review candidate, not proof of fraud, an error, or a confirmed accounting adjustment. The dashboard's net transaction-line measure is an analytical metric, not audited revenue or profit.

## What it does

- **Data profiling:** reports missing customer identifiers, exact duplicate candidates, cancellation invoices, non-positive quantities, and price concerns.
- **SQLite analytics:** loads the source records into SQLite while preserving raw transaction fields for later investigation.
- **Transparent revenue rules:** calculates gross positive sales using documented eligibility rules and retains cancellation/return records for separate analysis.
- **Robust anomaly detection:** compares daily values with earlier dates sharing the same weekday, using a median/MAD-based robust score when possible and a percentage-change fallback when historical MAD is zero.
- **Gross-versus-net comparison:** helps distinguish a gross-sales spike that is substantially offset by negative transaction values from a day that remains unusual on both metrics.
- **Reversal reconciliation:** ranks same-day positive/negative amount matches and compares product codes and absolute quantities. These are candidate relationships, not confirmed pairs.
- **Evidence-led dashboard:** explores daily metrics, potential anomalies, product and country summaries, data quality, SQLite records, and transaction-level evidence.
- **Automated checks:** a small pytest suite checks the central anomaly-scoring behaviour.

## Dataset

This project uses the **Online Retail** dataset from the UCI Machine Learning Repository. It contains 541,909 transaction lines from a UK-based online retailer, covering 1 December 2010 through 9 December 2011.

- Dataset page: <https://archive.ics.uci.edu/dataset/352/online+retail>
- Citation: Chen, D. (2015). *Online Retail* [Dataset]. UCI Machine Learning Repository. <https://doi.org/10.24432/C5BW33>
- License: CC BY 4.0. See the UCI page for attribution and license details.

The original Excel file, derived SQLite database, and generated reports are deliberately **not committed**. They are reproducible local artefacts and are excluded by `.gitignore` to keep the Git repository small and avoid committing data accidentally.

## Technology

- Python
- SQL and SQLite
- pandas and NumPy
- Streamlit
- pytest
- Optional local model experiments may use Ollama; the core analytics and dashboard do not require a paid AI API.

## Project structure

```text
TruthTrail/
├── main.py
├── load_retail_database.py
├── profile_retail_database.py
├── build_retail_analytics.py
├── detect_retail_anomalies.py
├── compare_gross_net_revenue.py
├── reconcile_retail_reversals.py
├── detect_gross_net_anomalies.py
├── retail_dashboard.py
├── requirements.txt
├── README.md
├── .gitignore
├── tests/
│   └── test_dual_metric.py
├── data/       # local only; ignored by Git
└── reports/    # generated outputs; ignored by Git
```

The repository may include additional exploratory scripts created during development. The list above highlights the core workflow.

## Setup on Windows

### 1. Clone the repository

```bat
git clone https://github.com/YOUR-USERNAME/TruthTrail.git
cd TruthTrail
```

Replace `YOUR-USERNAME` with your GitHub username and use your actual repository URL.

### 2. Create and activate a virtual environment

Python 3.13 was used during development. A recent supported Python 3 version should work with the listed dependencies.

```bat
py -3.13 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Download the source dataset

Download `Online Retail.xlsx` from the UCI dataset page linked above. In the project root, create the expected local folder and place the workbook here:

```text
data/raw/Online Retail.xlsx
```

In Windows Command Prompt:

```bat
mkdir data\raw
```

Do not add the workbook to Git; it is intentionally ignored.

### 4. Generate the local database and analytics

Run these commands from the project root, in order:

```bat
python load_retail_database.py
python profile_retail_database.py
python build_retail_analytics.py
python detect_retail_anomalies.py
python compare_gross_net_revenue.py
python reconcile_retail_reversals.py
python detect_gross_net_anomalies.py
```

The scripts create the local SQLite database and CSV reports used by the dashboard. Generated files are under `data/` and `reports/`; neither folder is committed to Git.

### 5. Launch the dashboard

```bat
streamlit run retail_dashboard.py
```

The dashboard reads the database and reports generated in the previous step. For the dual-metric and reversal evidence panels, run the corresponding comparison and reconciliation scripts above first.

### 6. Run automated tests

```bat
python -m pytest -q
```

## Current exploratory findings

On the analyzed version of the dataset, the project identified 5,268 extra rows belonging to exact-duplicate groups. Its initial gross-sales detector flagged 28 potential anomaly dates; the dual-metric detector flagged 24 net-value anomaly dates, with 17 dates flagged by both measures, 9 gross-only anomalies, 7 net-only anomalies, and 2 gross spikes classified as mostly offset by negative transaction values. These are detector outputs under the current rules, not measured accuracy or confirmed errors.

Some large negative transaction lines have same-day positive lines with the same absolute amount. Matching logic also checks product and quantity, but may produce ambiguous or reused candidates. Reconciliation therefore supports analyst review rather than automatically pairing or deleting transactions.

## Analytical definitions and limitations

- **Gross positive sales:** eligible positive-quantity lines excluding cancellation invoices, negative prices, and extra exact-duplicate candidates under the current project rules.
- **Net transaction-line value:** signed eligible line amounts after excluding extra exact-duplicate candidates and lines with negative unit prices; cancellation and negative-quantity values are retained.
- **Historical baseline:** up to eight earlier observations from the same weekday, with at least four observations required before using the robust detector.
- **MAD fallback:** when the historical median absolute deviation is zero, a percentage-change rule is used.
- **Interpretation:** unusual volume can reflect genuine bulk orders, seasonality, stock events, data entry issues, cancellations, or other causes. Context and business confirmation are required.
- **No accuracy claim:** the current exploration has not been evaluated against a verified ground-truth label set. Do not describe the flags as fraud detection or claim precision/recall until such an evaluation exists.

## Suggested next improvements

1. Add representative labelled test cases and benchmark false-positive/false-negative behaviour.
2. Add data-contract checks for schema, date parsing, row counts, and metric reconciliation.
3. Improve reversal matching so one positive line cannot be assigned to multiple negative lines without an explicit ambiguity label.
4. Add a reproducible CI test workflow (included) and screenshots of the dashboard to the repository once tested locally.
5. Optionally connect local AI to a compact, evidence-only incident summary. Keep the analytical result deterministic and label AI-generated commentary clearly.

## Attribution

Dataset: Chen, D. (2015). *Online Retail* [Dataset]. UCI Machine Learning Repository. <https://doi.org/10.24432/C5BW33>. Licensed under CC BY 4.0.
