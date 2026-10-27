
import json
import sqlite3
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "data" / "truthtrail.db"
REPORT_FILE = PROJECT_DIR / "reports" / "incident_evidence.json"

CHANGE_THRESHOLD = 50.0


def get_product_revenue(connection):
    query = """
    WITH ranked AS (
        SELECT *,
            NULLIF(TRIM(transaction_id), '') AS clean_id,
            ROW_NUMBER() OVER (
                PARTITION BY NULLIF(TRIM(transaction_id), '')
                ORDER BY row_id
            ) AS occurrence
        FROM transactions
    )
    SELECT
        order_date,
        product,
        SUM(
            CAST(quantity AS INTEGER) *
            CAST(unit_price AS REAL)
        ) AS revenue
    FROM ranked
    WHERE clean_id IS NOT NULL
      AND occurrence = 1
      AND LOWER(TRIM(COALESCE(payment_status, ''))) = 'paid'
      AND TRIM(COALESCE(quantity, '')) <> ''
      AND CAST(quantity AS INTEGER) > 0
      AND TRIM(COALESCE(unit_price, '')) <> ''
      AND CAST(unit_price AS REAL) >= 0
    GROUP BY order_date, product
    ORDER BY order_date, product
    """

    return connection.execute(query).fetchall()


def main():
    if not DB_FILE.exists():
        print("Database not found. Run python load_database.py first.")
        return

    with sqlite3.connect(DB_FILE) as connection:
        rows = get_product_revenue(connection)

    daily_products = {}

    for date, product, revenue in rows:
        daily_products.setdefault(date, {})
        daily_products[date][product or "(unknown)"] = revenue

    dates = sorted(daily_products)
    incidents = []

    for index in range(1, len(dates)):
        previous_date = dates[index - 1]
        current_date = dates[index]

        previous = daily_products[previous_date]
        current = daily_products[current_date]

        previous_total = sum(previous.values())
        current_total = sum(current.values())
        absolute_change = current_total - previous_total

        if previous_total == 0:
            if current_total == 0:
                continue
            percentage_change = None
            is_anomaly = True
        else:
            percentage_change = (
                absolute_change / abs(previous_total)
            ) * 100
            is_anomaly = abs(percentage_change) > CHANGE_THRESHOLD

        if not is_anomaly:
            continue

        products = set(previous) | set(current)
        contributors = []

        for product in products:
            difference = (
                current.get(product, 0)
                - previous.get(product, 0)
            )

            if difference != 0:
                contributors.append({
                    "product": product,
                    "revenue_change": round(difference, 2),
                })

        contributors.sort(
            key=lambda item: abs(item["revenue_change"]),
            reverse=True,
        )

        incidents.append({
            "previous_date": previous_date,
            "current_date": current_date,
            "previous_revenue": round(previous_total, 2),
            "current_revenue": round(current_total, 2),
            "absolute_change": round(absolute_change, 2),
            "percentage_change": (
                round(percentage_change, 2)
                if percentage_change is not None
                else None
            ),
            "threshold_percent": CHANGE_THRESHOLD,
            "largest_product_contributors": contributors[:5],
        })

    evidence = {
        "project": "TruthTrail",
        "report_type": "Revenue anomaly evidence",
        "detection_rule": (
            "Flag a change greater than the configured "
            "percentage threshold between consecutive "
            "available dates."
        ),
        "incidents": incidents,
        "limitations": [
            "An anomaly is not proof of an error.",
            "Product-level changes are contributors, "
            "not proof of the underlying cause.",
            "The current dataset contains very few dates."
        ],
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(evidence, indent=2),
        encoding="utf-8",
    )

    print("TruthTrail - Incident Evidence")
    print("-" * 40)
    print(f"Incidents recorded: {len(incidents)}")
    print(f"Evidence file: {REPORT_FILE}")


if __name__ == "__main__":
    main()
