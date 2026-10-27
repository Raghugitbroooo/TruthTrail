
import csv
from pathlib import Path


DATA_FILE = Path("data/raw/transactions.csv")


def check_transactions(file_path):
    issues = []
    seen_transaction_ids = set()

    with file_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)

        for row_number, row in enumerate(reader, start=2):
            transaction_id = row["transaction_id"].strip()

            # Check 1: Find duplicate transaction IDs
            if transaction_id in seen_transaction_ids:
                issues.append(
                    f"Row {row_number}: Duplicate transaction ID {transaction_id}"

                )
            else:
                seen_transaction_ids.add(transaction_id)

            # Check 2: Find missing customer IDs
            customer_id = row["customer_id"].strip()

            if not customer_id:
                issues.append(
                    f"Row {row_number}: Missing customer ID"
                )

            # Check 3: Find invalid quantities
            quantity = int(row["quantity"])

            if quantity <= 0:
                issues.append(
                    f"Row {row_number}: Invalid quantity {quantity}"
                )

            # Check 4: Find negative prices
            unit_price = float(row["unit_price"])

            if unit_price < 0:
                issues.append(
                    f"Row {row_number}: Negative unit price {unit_price}"
                )

    return issues


def main():
    print("TruthTrail - Data Quality Report")
    print("-" * 40)

    issues = check_transactions(DATA_FILE)

    if not issues:
        print("No data-quality issues found.")
    else:
        for issue in issues:
            print(f"[ISSUE] {issue}")

    print(f"\nTotal issues found: {len(issues)}")


if __name__ == "__main__":
    main()
