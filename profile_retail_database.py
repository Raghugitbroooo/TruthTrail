
import sqlite3
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "data" / "retail_truthtrail.db"


def get_value(connection, query):
    return connection.execute(query).fetchone()[0]


def main():
    if not DB_FILE.exists():
        print(f"Database not found: {DB_FILE}")
        print("Run python load_retail_database.py first.")
        return

    connection = sqlite3.connect(DB_FILE)

    try:
        print("TruthTrail - Retail Database Profile")
        print("=" * 48)

        total_rows = get_value(
            connection,
            "SELECT COUNT(*) FROM retail_transactions"
        )

        distinct_invoices = get_value(
            connection,
            """
            SELECT COUNT(DISTINCT invoice_no)
            FROM retail_transactions
            """
        )

        distinct_customers = get_value(
            connection,
            """
            SELECT COUNT(DISTINCT customer_id)
            FROM retail_transactions
            """
        )

        distinct_countries = get_value(
            connection,
            """
            SELECT COUNT(DISTINCT country)
            FROM retail_transactions
            """
        )

        missing_customers = get_value(
            connection,
            """
            SELECT COUNT(*)
            FROM retail_transactions
            WHERE customer_id IS NULL
               OR TRIM(customer_id) = ''
            """
        )

        missing_descriptions = get_value(
            connection,
            """
            SELECT COUNT(*)
            FROM retail_transactions
            WHERE description IS NULL
               OR TRIM(description) = ''
            """
        )

        cancellation_rows = get_value(
            connection,
            """
            SELECT COUNT(*)
            FROM retail_transactions
            WHERE is_cancellation_invoice = 1
            """
        )

        cancellation_invoices = get_value(
            connection,
            """
            SELECT COUNT(DISTINCT invoice_no)
            FROM retail_transactions
            WHERE is_cancellation_invoice = 1
            """
        )

        negative_quantity_rows = get_value(
            connection,
            """
            SELECT COUNT(*)
            FROM retail_transactions
            WHERE quantity < 0
            """
        )

        negative_price_rows = get_value(
            connection,
            """
            SELECT COUNT(*)
            FROM retail_transactions
            WHERE unit_price < 0
            """
        )

        duplicate_extra_rows = get_value(
            connection,
            """
            WITH grouped AS (
                SELECT
                    invoice_no,
                    stock_code,
                    description,
                    quantity,
                    invoice_date,
                    unit_price,
                    customer_id,
                    country,
                    COUNT(*) AS occurrences
                FROM retail_transactions
                GROUP BY
                    invoice_no,
                    stock_code,
                    description,
                    quantity,
                    invoice_date,
                    unit_price,
                    customer_id,
                    country
            )
            SELECT COALESCE(SUM(occurrences - 1), 0)
            FROM grouped
            WHERE occurrences > 1
            """
        )

        earliest_date, latest_date = connection.execute(
            """
            SELECT MIN(invoice_date), MAX(invoice_date)
            FROM retail_transactions
            """
        ).fetchone()

        sales_value, return_cancel_value, raw_net_value = (
            connection.execute(
                """
                SELECT
                    COALESCE(
                        SUM(
                            CASE
                                WHEN is_cancellation_invoice = 0
                                 AND quantity > 0
                                 AND unit_price >= 0
                                THEN line_amount
                                ELSE 0
                            END
                        ), 0
                    ),
                    COALESCE(
                        SUM(
                            CASE
                                WHEN is_cancellation_invoice = 1
                                  OR quantity < 0
                                THEN line_amount
                                ELSE 0
                            END
                        ), 0
                    ),
                    COALESCE(SUM(line_amount), 0)
                FROM retail_transactions
                """
            ).fetchone()
        )

        print(f"\nTransaction-line rows: {total_rows:,}")
        print(f"Distinct invoices: {distinct_invoices:,}")
        print(f"Distinct customers with IDs: {distinct_customers:,}")
        print(f"Countries: {distinct_countries:,}")

        print("\nDATA QUALITY")
        print(f"Missing customer IDs: {missing_customers:,}")
        print(f"Missing descriptions: {missing_descriptions:,}")
        print(f"Exact duplicate extra rows: {duplicate_extra_rows:,}")
        print(f"Cancellation invoice rows: {cancellation_rows:,}")
        print(f"Distinct cancellation invoices: {cancellation_invoices:,}")
        print(f"Negative quantity rows: {negative_quantity_rows:,}")
        print(f"Negative price rows: {negative_price_rows:,}")

        print("\nDATE RANGE")
        print(f"Earliest invoice: {earliest_date}")
        print(f"Latest invoice: {latest_date}")

        print("\nPRELIMINARY VALUE ANALYSIS")
        print(f"Positive-quantity sales value: {sales_value:,.2f}")
        print(f"Return/cancellation line value: {return_cancel_value:,.2f}")
        print(f"Unadjusted net line value: {raw_net_value:,.2f}")

        print("\nNote:")
        print("- Values are not assigned a currency here.")
        print("- These figures have not been deduplicated.")
        print("- Returns and cancellations require business-rule review.")
        print("- No source records were changed.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
