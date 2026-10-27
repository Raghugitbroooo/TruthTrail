
import sqlite3
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "data" / "retail_truthtrail.db"
ANOMALY_FILE = (
    PROJECT_DIR / "reports" / "retail_anomaly_findings.csv"
)
REPORT_DIR = PROJECT_DIR / "reports"

TOP_ANOMALIES = 5


def load_top_anomalies():
    if not ANOMALY_FILE.exists():
        raise FileNotFoundError(
            "Anomaly findings not found. "
            "Run python detect_retail_anomalies.py first."
        )

    findings = pd.read_csv(ANOMALY_FILE)

    findings["robust_z_score"] = pd.to_numeric(
        findings["robust_z_score"], errors="coerce"
    )

    findings = findings[
        findings["status"] == "Potential anomaly"
    ].copy()

    findings["absolute_z_score"] = (
        findings["robust_z_score"].abs()
    )

    findings = findings.sort_values(
        "absolute_z_score",
        ascending=False,
    )

    return findings.head(TOP_ANOMALIES)


def get_daily_diagnostics(connection, date_text):
    query = """
        SELECT
            COUNT(*) AS source_rows,

            SUM(CASE
                WHEN is_cancellation_invoice = 1 THEN 1
                ELSE 0
            END) AS cancellation_rows,

            SUM(CASE
                WHEN quantity <= 0 THEN 1
                ELSE 0
            END) AS non_positive_quantity_rows,

            SUM(CASE
                WHEN unit_price < 0 THEN 1
                ELSE 0
            END) AS negative_price_rows,

            SUM(CASE
                WHEN exact_duplicate_rank > 1 THEN 1
                ELSE 0
            END) AS duplicate_extra_rows,

            SUM(CASE
                WHEN exact_duplicate_rank = 1
                 AND is_cancellation_invoice = 0
                 AND quantity > 0
                 AND unit_price >= 0
                THEN 1 ELSE 0
            END) AS eligible_sales_lines,

            COUNT(DISTINCT CASE
                WHEN exact_duplicate_rank = 1
                 AND is_cancellation_invoice = 0
                 AND quantity > 0
                 AND unit_price >= 0
                THEN invoice_no
            END) AS eligible_invoices,

            SUM(CASE
                WHEN exact_duplicate_rank = 1
                 AND is_cancellation_invoice = 0
                 AND quantity > 0
                 AND unit_price >= 0
                THEN line_amount
                ELSE 0
            END) AS gross_sales_gbp

        FROM retail_analysis_stage
        WHERE SUBSTR(invoice_date, 1, 10) = ?
    """

    return connection.execute(
        query, (date_text,)
    ).fetchone()


def get_top_products(connection, date_text):
    query = """
        SELECT
            stock_code,
            MAX(description) AS description,
            SUM(quantity) AS units,
            COUNT(DISTINCT invoice_no) AS invoices,
            SUM(line_amount) AS sales_gbp

        FROM retail_analysis_stage

        WHERE SUBSTR(invoice_date, 1, 10) = ?
          AND exact_duplicate_rank = 1
          AND is_cancellation_invoice = 0
          AND quantity > 0
          AND unit_price >= 0

        GROUP BY stock_code
        ORDER BY sales_gbp DESC
        LIMIT 5
    """

    return connection.execute(
        query, (date_text,)
    ).fetchall()


def get_top_invoices(connection, date_text):
    query = """
        SELECT
            invoice_no,
            MAX(customer_id) AS customer_id,
            MAX(country) AS country,
            COUNT(*) AS product_lines,
            SUM(line_amount) AS sales_gbp

        FROM retail_analysis_stage

        WHERE SUBSTR(invoice_date, 1, 10) = ?
          AND exact_duplicate_rank = 1
          AND is_cancellation_invoice = 0
          AND quantity > 0
          AND unit_price >= 0

        GROUP BY invoice_no
        ORDER BY sales_gbp DESC
        LIMIT 5
    """

    return connection.execute(
        query, (date_text,)
    ).fetchall()


def main():
    if not DB_FILE.exists():
        raise FileNotFoundError(
            f"Retail database not found: {DB_FILE}"
        )

    anomalies = load_top_anomalies()

    if anomalies.empty:
        print("No potential anomalies were available to investigate.")
        return

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_FILE) as connection:
        maximum_timestamp = connection.execute("""
            SELECT MAX(invoice_date)
            FROM retail_transactions
        """).fetchone()[0]

        final_dataset_date = (
            maximum_timestamp[:10]
            if maximum_timestamp
            else None
        )

        print("TruthTrail - Retail Anomaly Investigation")
        print("=" * 48)
        print(f"Investigating top {len(anomalies)} anomalies.")
        print(f"Latest source timestamp: {maximum_timestamp}")

        product_exports = []
        invoice_exports = []
        summary_exports = []

        for _, anomaly in anomalies.iterrows():
            date_text = pd.Timestamp(
                anomaly["date"]
            ).strftime("%Y-%m-%d")

            print("\n" + "=" * 48)
            print(f"Date: {date_text}")
            print(f"Weekday: {anomaly['weekday']}")
            print(
                f"Actual gross sales: "
                f"£{anomaly['gross_sales_gbp']:,.2f}"
            )
            print(
                f"Historical median: "
                f"£{anomaly['baseline_median_gbp']:,.2f}"
            )
            print(
                f"Change from baseline: "
                f"{anomaly['change_from_baseline_pct']:+.2f}%"
            )
            print(
                f"Robust z-score: "
                f"{anomaly['robust_z_score']:.3f}"
            )

            if date_text == final_dataset_date:
                print(
                    "DATA-COVERAGE WARNING: This is the final "
                    "date in the source dataset. It may represent "
                    "an incomplete trading day."
                )

            diagnostics = get_daily_diagnostics(
                connection, date_text
            )

            (
                source_rows,
                cancellation_rows,
                non_positive_rows,
                negative_price_rows,
                duplicate_rows,
                eligible_lines,
                eligible_invoices,
                gross_sales,
            ) = diagnostics

            # Handle any SQL aggregate that returns NULL.
            source_rows = source_rows or 0
            cancellation_rows = cancellation_rows or 0
            non_positive_rows = non_positive_rows or 0
            negative_price_rows = negative_price_rows or 0
            duplicate_rows = duplicate_rows or 0
            eligible_lines = eligible_lines or 0
            eligible_invoices = eligible_invoices or 0
            gross_sales = gross_sales or 0.0

            print("\nRecord diagnostics:")
            print(f"Source rows: {source_rows:,}")
            print(f"Eligible sales lines: {eligible_lines:,}")
            print(f"Eligible invoices: {eligible_invoices:,}")
            print(f"Cancellation rows: {cancellation_rows:,}")
            print(
                f"Non-positive quantity rows: "
                f"{non_positive_rows:,}"
            )
            print(f"Negative price rows: {negative_price_rows:,}")
            print(
                f"Extra exact-duplicate candidates: "
                f"{duplicate_rows:,}"
            )

            summary_exports.append({
                "date": date_text,
                "gross_sales_gbp": gross_sales,
                "baseline_median_gbp": anomaly[
                    "baseline_median_gbp"
                ],
                "change_from_baseline_pct": anomaly[
                    "change_from_baseline_pct"
                ],
                "robust_z_score": anomaly["robust_z_score"],
                "source_rows": source_rows,
                "eligible_sales_lines": eligible_lines,
                "eligible_invoices": eligible_invoices,
                "cancellation_rows": cancellation_rows,
                "non_positive_quantity_rows": non_positive_rows,
                "negative_price_rows": negative_price_rows,
                "duplicate_extra_rows": duplicate_rows,
            })

            print("\nTop products contributing to gross sales:")

            for stock_code, description, units, invoices, sales in (
                get_top_products(connection, date_text)
            ):
                print(
                    f"- {stock_code} | {description} | "
                    f"units={units:,.0f} | invoices={invoices:,} | "
                    f"sales=£{sales:,.2f}"
                )

                product_exports.append({
                    "date": date_text,
                    "stock_code": stock_code,
                    "description": description,
                    "units": units,
                    "invoices": invoices,
                    "sales_gbp": sales,
                })

            print("\nLargest eligible invoices:")

            for invoice, customer, country, lines, sales in (
                get_top_invoices(connection, date_text)
            ):
                customer_text = (
                    customer
                    if customer is not None
                    else "(unknown)"
                )

                print(
                    f"- Invoice {invoice} | "
                    f"customer={customer_text} | country={country} | "
                    f"lines={lines} | sales=£{sales:,.2f}"
                )

                invoice_exports.append({
                    "date": date_text,
                    "invoice_no": invoice,
                    "customer_id": customer,
                    "country": country,
                    "product_lines": lines,
                    "sales_gbp": sales,
                })

    pd.DataFrame(summary_exports).to_csv(
        REPORT_DIR / "retail_anomaly_investigation_summary.csv",
        index=False,
    )

    pd.DataFrame(product_exports).to_csv(
        REPORT_DIR / "retail_anomaly_product_drivers.csv",
        index=False,
    )

    pd.DataFrame(invoice_exports).to_csv(
        REPORT_DIR / "retail_anomaly_invoice_drivers.csv",
        index=False,
    )

    print("\n" + "=" * 48)
    print("Investigation completed.")
    print("Three investigation CSV reports were saved to:")
    print(REPORT_DIR)
    print(
        "\nProduct and invoice contributions explain the measured "
        "sales total; they do not prove the underlying business cause."
    )


if __name__ == "__main__":
    main()
