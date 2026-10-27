
import csv
from pathlib import Path


DATA_FILE = Path("data/raw/transactions.csv")


def calculate_trusted_revenue(file_path):
    seen_transaction_ids = set()

    total_revenue = 0.0
    accepted_transactions = 0
    rows_read = 0

    skipped = {
        "duplicates": 0,
        "not_paid": 0,
        "invalid_quantity": 0,
        "invalid_price": 0,
        "invalid_number": 0,
        "missing_transaction_id": 0,
    }

    with file_path.open(
        "r", newline="", encoding="utf-8-sig"
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        for row in reader:
            rows_read += 1

            transaction_id = row["transaction_id"].strip()

            if not transaction_id:
                skipped["missing_transaction_id"] += 1
                continue

            if transaction_id in seen_transaction_ids:
                skipped["duplicates"] += 1
                continue

            seen_transaction_ids.add(transaction_id)

            if row["payment_status"].strip().lower() != "paid":
                skipped["not_paid"] += 1
                continue

            try:
                quantity = int(row["quantity"])
                unit_price = float(row["unit_price"])
            except ValueError:
                skipped["invalid_number"] += 1
                continue

            if quantity <= 0:
                skipped["invalid_quantity"] += 1
                continue

            if unit_price < 0:
                skipped["invalid_price"] += 1
                continue

            total_revenue += quantity * unit_price
            accepted_transactions += 1

    return {
        "rows_read": rows_read,
        "accepted_transactions": accepted_transactions,
        "total_revenue": total_revenue,
        "skipped": skipped,
    }


def main():
    results = calculate_trusted_revenue(DATA_FILE)

    print("TruthTrail - Revenue Analysis")
    print("-" * 40)
    print(f"Rows read: {results['rows_read']}")
    print(
        "Revenue-eligible transactions: "
        f"{results['accepted_transactions']}"
    )

    for reason, count in results["skipped"].items():
        print(f"Skipped for {reason}: {count}")

    print(
        "\nTotal revenue: "
        f"{results['total_revenue']:,.2f}"
    )


if __name__ == "__main__":
    main()
