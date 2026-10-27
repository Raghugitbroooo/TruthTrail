
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
DATA_FILE = PROJECT_DIR / "data" / "raw" / "Online Retail.xlsx"


def main():
    print("TruthTrail - Retail Dataset Inspection")
    print("=" * 45)

    if not DATA_FILE.exists():
        print(f"File not found: {DATA_FILE}")
        print("Check the filename in data/raw and try again.")
        return

    print("Reading Excel data. This may take a little time...")

    df = pd.read_excel(DATA_FILE, engine="openpyxl")

    print("\n1. DATASET SIZE")
    print(f"Transaction-line records: {len(df):,}")
    print(f"Columns: {len(df.columns)}")

    print("\n2. COLUMN NAMES")
    for column in df.columns:
        print(f"- {column}")

    print("\n3. FIRST FIVE RECORDS")
    print(df.head().to_string(index=False))

    print("\n4. MISSING VALUES")
    missing = df.isna().sum()
    for column, count in missing.items():
        print(f"{column}: {count:,}")

    print("\n5. BUSINESS METRICS")
    if "InvoiceNo" in df.columns:
        invoices = df["InvoiceNo"].astype("string").str.strip()

        print(f"Distinct invoice numbers: {invoices.nunique():,}")

        cancellations = invoices.str.startswith(
            "C", na=False
        )

        print(
            "Rows with cancellation invoice numbers: "
            f"{cancellations.sum():,}"
        )

    if "CustomerID" in df.columns:
        print(
            "Distinct non-missing customers: "
            f"{df['CustomerID'].nunique():,}"
        )

    if "Country" in df.columns:
        print(f"Countries: {df['Country'].nunique():,}")

    print("\n6. QUANTITY AND PRICE CHECKS")

    if "Quantity" in df.columns:
        quantity = pd.to_numeric(
            df["Quantity"], errors="coerce"
        )

        print(f"Zero or negative quantities: {(quantity <= 0).sum():,}")
        print(f"Invalid or missing quantities: {quantity.isna().sum():,}")

    if "UnitPrice" in df.columns:
        price = pd.to_numeric(
            df["UnitPrice"], errors="coerce"
        )

        print(f"Negative unit prices: {(price < 0).sum():,}")
        print(f"Invalid or missing prices: {price.isna().sum():,}")

    print("\n7. DUPLICATE RECORD CHECK")

    duplicate_rows = df.duplicated().sum()
    print(f"Fully duplicated rows: {duplicate_rows:,}")

    print(
        "Note: repeated invoice numbers are not necessarily "
        "duplicates because one invoice may contain multiple products."
    )

    print("\n8. DATE RANGE")

    if "InvoiceDate" in df.columns:
        dates = pd.to_datetime(
            df["InvoiceDate"], errors="coerce"
        )

        print(f"Earliest invoice: {dates.min()}")
        print(f"Latest invoice: {dates.max()}")
        print(f"Invalid or missing dates: {dates.isna().sum():,}")

    print("\nInspection completed.")
    print("No source records were modified.")


if __name__ == "__main__":
    main()
