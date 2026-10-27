import csv
import sqlite3
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
CSV_FILE = PROJECT_DIR / "data" / "raw" / "transactions.csv"
DB_FILE = PROJECT_DIR / "data" / "truthtrail.db"

REQUIRED_COLUMNS = [
    "transaction_id",
    "order_date",
    "customer_id",
    "product",
    "quantity",
    "unit_price",
    "payment_status",
]


def load_transactions():
    if not CSV_FILE.exists():
        raise FileNotFoundError(f"CSV file not found: {CSV_FILE}")

    with CSV_FILE.open(
        "r", newline="", encoding="utf-8-sig"
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        if reader.fieldnames is None:
            raise ValueError("The CSV file is empty.")

        missing_columns = set(REQUIRED_COLUMNS) - set(reader.fieldnames)

        if missing_columns:
            raise ValueError(
                f"Missing CSV columns: {sorted(missing_columns)}"
            )

        rows = []

        for row in reader:
            cleaned_row = tuple(
                (row.get(column) or "").strip() or None
                for column in REQUIRED_COLUMNS
            )
            rows.append(cleaned_row)

    connection = sqlite3.connect(DB_FILE)

    try:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT,
                    order_date TEXT,
                    customer_id TEXT,
                    product TEXT,
                    quantity TEXT,
                    unit_price TEXT,
                    payment_status TEXT
                )
            """)

            # Clear previous imported data so reruns
            # do not insert duplicate copies.
            connection.execute("DELETE FROM transactions")

            connection.executemany("""
                INSERT INTO transactions (
                    transaction_id,
                    order_date,
                    customer_id,
                    product,
                    quantity,
                    unit_price,
                    payment_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)

        count = connection.execute(
            "SELECT COUNT(*) FROM transactions"
        ).fetchone()[0]

    finally:
        connection.close()

    print("TruthTrail - Database Loader")
    print("-" * 40)
    print(f"Rows imported: {count}")
    print(f"Database created at: {DB_FILE}")


if __name__ == "__main__":
    load_transactions()