
import sqlite3
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "data" / "retail_truthtrail.db"
ANOMALY_FILE = (
    PROJECT_DIR / "reports" / "retail_anomaly_findings.csv"
)
OUTPUT_FILE = (
    PROJECT_DIR / "reports" / "retail_suspicious_transaction_lines.csv"
)

TOP_ANOMALIES = 5
LINES_PER_DATE = 10

HIGH_VALUE_THRESHOLD = 10_000.00
HIGH_QUANTITY_THRESHOLD = 1_000


def load_top_anomaly_dates():
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
    ].dropna(subset=["robust_z_score"]).copy()

    findings["absolute_z_score"] = (
        findings["robust_z_score"].abs()
    )

    findings = findings.sort_values(
        "absolute_z_score", ascending=False
    )

    return findings.head(TOP_ANOMALIES)


def main():
    if not DB_FILE.exists():
        raise FileNotFoundError(
            f"Retail database not found: {DB_FILE}"
        )

    anomaly_dates = load_top_anomaly_dates()

    if anomaly_dates.empty:
        print("No potential anomalies available for investigation.")
        return

    selected_rows = []

    query = """
        SELECT
            row_id,
            invoice_no,
            stock_code,
            description,
            quantity,
            invoice_date,
            unit_price,
            customer_id,
            country,
            is_cancellation_invoice,
            line_amount,
            exact_duplicate_rank

        FROM retail_analysis_stage

        WHERE SUBSTR(invoice_date, 1, 10) = ?

        ORDER BY ABS(COALESCE(line_amount, 0)) DESC

        LIMIT ?
    """

    with sqlite3.connect(DB_FILE) as connection:
        print("TruthTrail - Transaction Line Investigation")
        print("=" * 48)

        for _, anomaly in anomaly_dates.iterrows():
            date_text = pd.Timestamp(
                anomaly["date"]
            ).strftime("%Y-%m-%d")

            rows = connection.execute(
                query,
                (date_text, LINES_PER_DATE),
            ).fetchall()

            print(f"\nDate: {date_text}")
            print(
                f"Revenue baseline change: "
                f"{anomaly['change_from_baseline_pct']:+.2f}%"
            )

            for row in rows:
                (
                    row_id,
                    invoice_no,
                    stock_code,
                    description,
                    quantity,
                    invoice_date,
                    unit_price,
                    customer_id,
                    country,
                    is_cancellation,
                    line_amount,
                    duplicate_rank,
                ) = row

                flags = []

                if abs(line_amount or 0) >= HIGH_VALUE_THRESHOLD:
                    flags.append("HIGH_LINE_VALUE_REVIEW")

                if abs(quantity or 0) >= HIGH_QUANTITY_THRESHOLD:
                    flags.append("HIGH_QUANTITY_REVIEW")

                if is_cancellation:
                    flags.append("CANCELLATION_INVOICE")

                if (quantity or 0) <= 0:
                    flags.append("NON_POSITIVE_QUANTITY")

                if (unit_price or 0) < 0:
                    flags.append("NEGATIVE_UNIT_PRICE")

                if (duplicate_rank or 0) > 1:
                    flags.append("EXACT_DUPLICATE_CANDIDATE")

                if not customer_id:
                    flags.append("MISSING_CUSTOMER_ID")

                if not flags:
                    flags.append("NO_RULE_BASED_FLAG")

                selected_rows.append({
                    "analysis_date": date_text,
                    "row_id": row_id,
                    "invoice_no": invoice_no,
                    "stock_code": stock_code,
                    "description": description,
                    "quantity": quantity,
                    "invoice_date": invoice_date,
                    "unit_price": unit_price,
                    "line_amount": line_amount,
                    "customer_id": customer_id,
                    "country": country,
                    "is_cancellation_invoice": is_cancellation,
                    "exact_duplicate_rank": duplicate_rank,
                    "review_flags": "; ".join(flags),
                })

                print(
                    f"  Invoice {invoice_no} | "
                    f"Product {stock_code} | "
                    f"Qty {quantity} | "
                    f"Price {unit_price} | "
                    f"Line value {line_amount:,.2f} | "
                    f"{'; '.join(flags)}"
                )

    result = pd.DataFrame(selected_rows)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False)

    print("\n" + "=" * 48)
    print(f"Anomaly dates examined: {len(anomaly_dates)}")
    print(f"Transaction lines exported: {len(result)}")
    print(f"Review report saved to: {OUTPUT_FILE}")

    print(
        "\nReview flags identify records for investigation; "
        "they do not establish that a transaction is erroneous."
    )


if __name__ == "__main__":
    main()
