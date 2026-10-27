
import sqlite3
from pathlib import Path


DB_FILE = Path(__file__).resolve().parent / "data" / "truthtrail.db"


def main():
    if not DB_FILE.exists():
        print("Database not found. Run python load_database.py first.")
        return

    query = """
    WITH ranked AS (
        SELECT
            *,
            NULLIF(TRIM(transaction_id), '') AS clean_id,
            ROW_NUMBER() OVER (
                PARTITION BY NULLIF(TRIM(transaction_id), '')
                ORDER BY row_id
            ) AS occurrence
        FROM transactions
    ),
    classified AS (
        SELECT *,
            CASE
                WHEN clean_id IS NULL
                    THEN 'missing_transaction_id'
                WHEN occurrence > 1
                    THEN 'duplicate'
                WHEN LOWER(TRIM(payment_status)) <> 'paid'
                    THEN 'not_paid'
                WHEN TRIM(COALESCE(quantity, '')) = ''
                     OR CAST(quantity AS INTEGER) <= 0
                    THEN 'invalid_quantity'
                WHEN TRIM(COALESCE(unit_price, '')) = ''
                     OR CAST(unit_price AS REAL) < 0
                    THEN 'invalid_price'
                ELSE 'accepted'
            END AS decision
        FROM ranked
    )
    SELECT
        decision,
        COUNT(*) AS record_count,
        COALESCE(
            SUM(
                CASE
                    WHEN decision = 'accepted'
                    THEN CAST(quantity AS INTEGER)
                         * CAST(unit_price AS REAL)
                    ELSE 0
                END
            ), 0
        ) AS revenue
    FROM classified
    GROUP BY decision
    """

    with sqlite3.connect(DB_FILE) as connection:
        results = connection.execute(query).fetchall()

    summary = {
        decision: (count, revenue)
        for decision, count, revenue in results
    }

    print("TruthTrail - SQL Revenue Analysis")
    print("-" * 42)

    total_rows = sum(count for count, _ in summary.values())
    accepted_count, revenue = summary.get("accepted", (0, 0))

    print(f"Rows examined: {total_rows}")
    print(f"Accepted transactions: {accepted_count}")
    print(f"Total revenue: {revenue:,.2f}")

    print("\nRecord breakdown:")
    for decision, (count, _) in sorted(summary.items()):
        print(f"{decision}: {count}")


if __name__ == "__main__":
    main()
