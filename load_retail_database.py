
from itertools import islice
import sqlite3
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
SOURCE_FILE = PROJECT_DIR / "data" / "raw" / "Online Retail.xlsx"
DB_FILE = PROJECT_DIR / "data" / "retail_truthtrail.db"

CHUNK_SIZE = 10_000

REQUIRED_COLUMNS = [
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
]


def load_and_prepare_data():
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(
            f"Retail Excel file not found: {SOURCE_FILE}"
        )

    print("Reading retail dataset...")
    df = pd.read_excel(SOURCE_FILE, engine="openpyxl")

    missing_columns = set(REQUIRED_COLUMNS) - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"Missing expected columns: {sorted(missing_columns)}"
        )

    print(f"Source records: {len(df):,}")
    print("Preparing database records...")

    # Preserve invoice identifiers as text.
    invoice_no = df["InvoiceNo"].map(
        lambda value: str(value).strip()
        if pd.notna(value) else None
    )

    stock_code = df["StockCode"].map(
        lambda value: str(value).strip()
        if pd.notna(value) else None
    )

    description = df["Description"].map(
        lambda value: str(value).strip()
        if pd.notna(value) else None
    )

    country = df["Country"].map(
        lambda value: str(value).strip()
        if pd.notna(value) else None
    )

    # Retain missing customer IDs as NULL, not the text "nan".
    customer_numeric = pd.to_numeric(
        df["CustomerID"], errors="coerce"
    )

    customer_id = customer_numeric.map(
        lambda value: str(int(value))
        if pd.notna(value) else None
    )

    quantity_numeric = pd.to_numeric(
        df["Quantity"], errors="coerce"
    )

    price_numeric = pd.to_numeric(
        df["UnitPrice"], errors="coerce"
    )

    dates = pd.to_datetime(
        df["InvoiceDate"], errors="coerce"
    )

    invoice_date = dates.map(
        lambda value: value.strftime("%Y-%m-%d %H:%M:%S")
        if pd.notna(value) else None
    )

    quantity = quantity_numeric.map(
        lambda value: float(value)
        if pd.notna(value) else None
    )

    unit_price = price_numeric.map(
        lambda value: float(value)
        if pd.notna(value) else None
    )

    is_cancellation = (
        invoice_no.str.upper()
        .str.startswith("C", na=False)
        .astype(int)
    )

    line_amount = [
        qty * price if qty is not None and price is not None else None
        for qty, price in zip(quantity, unit_price)
    ]

    prepared = pd.DataFrame({
        "invoice_no": invoice_no,
        "stock_code": stock_code,
        "description": description,
        "quantity": quantity,
        "invoice_date": invoice_date,
        "unit_price": unit_price,
        "customer_id": customer_id,
        "country": country,
        "is_cancellation_invoice": is_cancellation,
        "line_amount": line_amount,
    })

    return prepared


def main():
    prepared = load_and_prepare_data()

    DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading into separate database: {DB_FILE}")

    connection = sqlite3.connect(DB_FILE)

    try:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS retail_transactions (
                    row_id INTEGER PRIMARY KEY,
                    invoice_no TEXT,
                    stock_code TEXT,
                    description TEXT,
                    quantity REAL,
                    invoice_date TEXT,
                    unit_price REAL,
                    customer_id TEXT,
                    country TEXT,
                    is_cancellation_invoice INTEGER NOT NULL,
                    line_amount REAL
                )
            """)

            # This replaces only the data in our new retail table.
            # The original truthtrail.db is not touched.
            connection.execute("DELETE FROM retail_transactions")

            insert_sql = """
                INSERT INTO retail_transactions (
                    invoice_no,
                    stock_code,
                    description,
                    quantity,
                    invoice_date,
                    unit_price,
                    customer_id,
                    country,
                    is_cancellation_invoice,
                    line_amount
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            row_iterator = prepared.itertuples(
                index=False, name=None
            )

            imported = 0

            while True:
                batch = list(islice(row_iterator, CHUNK_SIZE))

                if not batch:
                    break

                connection.executemany(insert_sql, batch)
                imported += len(batch)

                print(f"Imported {imported:,} / {len(prepared):,}")

            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_retail_invoice_date
                ON retail_transactions(invoice_date)
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_retail_invoice_no
                ON retail_transactions(invoice_no)
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_retail_customer
                ON retail_transactions(customer_id)
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_retail_country
                ON retail_transactions(country)
            """)

        # Verify the committed data.
        total_rows = connection.execute(
            "SELECT COUNT(*) FROM retail_transactions"
        ).fetchone()[0]

        cancellation_rows = connection.execute("""
            SELECT COUNT(*)
            FROM retail_transactions
            WHERE is_cancellation_invoice = 1
        """).fetchone()[0]

        missing_customers = connection.execute("""
            SELECT COUNT(*)
            FROM retail_transactions
            WHERE customer_id IS NULL
        """).fetchone()[0]

        print("\nRetail database import completed.")
        print(f"Rows imported: {total_rows:,}")
        print(f"Cancellation invoice rows: {cancellation_rows:,}")
        print(f"Missing customer IDs: {missing_customers:,}")
        print(f"Database: {DB_FILE}")
        print("Original prototype database was not modified.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
