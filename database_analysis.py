import sqlite3
from pathlib import Path


DB_FILE = Path(__file__).resolve().parent / "data" / "truthtrail.db"


def main():
    if not DB_FILE.exists():
        print("Database not found. Run python load_database.py first.")
        return

    connection = sqlite3.connect(DB_FILE)

    try:
        total_rows = connection.execute(
            "SELECT COUNT(*) FROM transactions"
        ).fetchone()[0]

        print("TruthTrail - SQL Data Quality Report")
        print("-" * 45)
        print(f"Rows examined: {total_rows}")

        issues_found = 0

        # 1. Find duplicate transaction IDs.
        duplicates = connection.execute("""
            SELECT transaction_id, COUNT(*) AS occurrences
            FROM transactions
            WHERE transaction_id IS NOT NULL
              AND TRIM(transaction_id) <> ''
            GROUP BY transaction_id
            HAVING COUNT(*) > 1
        """).fetchall()

        for transaction_id, count in duplicates:
            print(
                f"[ISSUE] Transaction ID {transaction_id} "
                f"appears {count} times."
            )
            issues_found += 1

        # 2. Find missing customer IDs.
        missing_customers = connection.execute("""
            SELECT row_id, transaction_id
            FROM transactions
            WHERE customer_id IS NULL
               OR TRIM(customer_id) = ''
        """).fetchall()

        for row_id, transaction_id in missing_customers:
            print(
                f"[ISSUE] Missing customer ID in "
                f"transaction {transaction_id}."
            )
            issues_found += 1

        # 3. Find invalid quantities.
        invalid_quantities = connection.execute("""
            SELECT row_id, transaction_id, quantity
            FROM transactions
            WHERE quantity IS NULL
               OR TRIM(quantity) = ''
               OR CAST(quantity AS INTEGER) <= 0
        """).fetchall()

        for row_id, transaction_id, quantity in invalid_quantities:
            print(
                f"[ISSUE] Invalid quantity {quantity} "
                f"in transaction {transaction_id}."
            )
            issues_found += 1

        # 4. Find negative unit prices.
        negative_prices = connection.execute("""
            SELECT row_id, transaction_id, unit_price
            FROM transactions
            WHERE unit_price IS NOT NULL
              AND TRIM(unit_price) <> ''
              AND CAST(unit_price AS REAL) < 0
        """).fetchall()

        for row_id, transaction_id, unit_price in negative_prices:
            print(
                f"[ISSUE] Negative price {unit_price} "
                f"in transaction {transaction_id}."
            )
            issues_found += 1

        print(f"\nTotal issue findings: {issues_found}")

    finally:
        connection.close()


if __name__ == "__main__":
    main()