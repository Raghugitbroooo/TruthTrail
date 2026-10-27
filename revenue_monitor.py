
import sqlite3
from pathlib import Path


DB_FILE = Path(__file__).resolve().parent / "data" / "truthtrail.db"
CHANGE_THRESHOLD = 50.0


def get_daily_revenue(connection):
    query = """
    WITH ranked AS (
        SELECT *,
            NULLIF(TRIM(transaction_id), '') AS clean_id,
            ROW_NUMBER() OVER (
                PARTITION BY NULLIF(TRIM(transaction_id), '')
                ORDER BY row_id
            ) AS occurrence
        FROM transactions
    ),
    accepted AS (
        SELECT *
        FROM ranked
        WHERE clean_id IS NOT NULL
          AND occurrence = 1
          AND LOWER(TRIM(COALESCE(payment_status, ''))) = 'paid'
          AND TRIM(COALESCE(quantity, '')) <> ''
          AND CAST(quantity AS INTEGER) > 0
          AND TRIM(COALESCE(unit_price, '')) <> ''
          AND CAST(unit_price AS REAL) >= 0
    )
    SELECT
        order_date,
        SUM(
            CAST(quantity AS INTEGER) *
            CAST(unit_price AS REAL)
        ) AS revenue
    FROM accepted
    GROUP BY order_date
    ORDER BY order_date
    """

    return connection.execute(query).fetchall()


def main():
    if not DB_FILE.exists():
        print("Database not found. Run python load_database.py first.")
        return

    with sqlite3.connect(DB_FILE) as connection:
        daily_results = get_daily_revenue(connection)

    print("TruthTrail - Daily Revenue Monitor")
    print("-" * 45)

    previous_revenue = None
    anomalies_found = 0

    for order_date, revenue in daily_results:
        print(f"\nDate: {order_date}")
        print(f"Revenue: {revenue:,.2f}")

        if previous_revenue is not None:
            if previous_revenue == 0:
                if revenue != 0:
                    print("[ALERT] Revenue changed from zero.")
                    anomalies_found += 1
            else:
                change = (
                    (revenue - previous_revenue)
                    / abs(previous_revenue)
                ) * 100

                print(f"Change from previous day: {change:+.2f}%")

                if abs(change) > CHANGE_THRESHOLD:
                    print(
                        "[ALERT] Unusual revenue change detected!"
                    )
                    anomalies_found += 1

        previous_revenue = revenue

    print("\n" + "-" * 45)
    print(f"Potential anomalies flagged: {anomalies_found}")
    print("Note: Alerts require investigation; they are not proof of an error.")


if __name__ == "__main__":
    main()
