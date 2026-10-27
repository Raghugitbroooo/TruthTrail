from pathlib import Path
import re
import sqlite3

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "data" / "retail_truthtrail.db"
OUTPUT_PATH = (
    PROJECT_DIR
    / "reports"
    / "retail_reversal_reconciliation.csv"
)

MIN_ABSOLUTE_VALUE = 1000.00
AMOUNT_TOLERANCE = 0.01
QUANTITY_TOLERANCE = 0.000001


def normalize_code(value):
    """Normalize product codes for comparison."""
    if pd.isna(value):
        return ""
    return str(value).strip().casefold()


def invoice_number(value):
    """Extract digits from invoice identifiers such as C581484."""
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def numeric_value(value):
    """Safely convert a value to float."""
    try:
        result = float(value)
        if pd.isna(result):
            return 0.0
        return result
    except (TypeError, ValueError):
        return 0.0


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}\n"
            "Run load_retail_database.py first."
        )

    print("TruthTrail - Cancellation Reconciliation Audit")
    print("=" * 52)
    print(f"Loading records from: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as connection:
        # Use one representative of each exact-duplicate group.
        # The original raw records remain untouched in the database.
        query = """
            SELECT
                row_id,
                invoice_no,
                stock_code,
                description,
                quantity,
                invoice_date,
                unit_price,
                line_amount,
                customer_id,
                country,
                is_cancellation_invoice,
                exact_duplicate_rank
            FROM retail_analysis_stage
            WHERE exact_duplicate_rank = 1
        """
        data = pd.read_sql_query(query, connection)

    if data.empty:
        print("No records were returned from retail_analysis_stage.")
        return

    data["quantity"] = pd.to_numeric(
        data["quantity"], errors="coerce"
    )
    data["unit_price"] = pd.to_numeric(
        data["unit_price"], errors="coerce"
    )
    data["line_amount"] = pd.to_numeric(
        data["line_amount"], errors="coerce"
    )
    data["invoice_date"] = pd.to_datetime(
        data["invoice_date"], errors="coerce"
    )
    data["transaction_date"] = (
        data["invoice_date"].dt.strftime("%Y-%m-%d")
    )

    data["is_cancellation_invoice"] = (
        pd.to_numeric(
            data["is_cancellation_invoice"], errors="coerce"
        )
        .fillna(0)
        .astype(int)
    )

    data["normalized_product"] = data["stock_code"].apply(
        normalize_code
    )

    # Potential original sale lines: positive amount and quantity,
    # not a cancellation invoice, and above our value threshold.
    positive_lines = data[
        (data["is_cancellation_invoice"] == 0)
        & (data["quantity"] > 0)
        & (data["unit_price"] >= 0)
        & (data["line_amount"] >= MIN_ABSOLUTE_VALUE)
    ].copy()

    # Potential reversals: negative line value and either a
    # cancellation invoice or a non-positive quantity.
    negative_lines = data[
        (data["line_amount"] <= -MIN_ABSOLUTE_VALUE)
        & (
            (data["is_cancellation_invoice"] == 1)
            | (data["quantity"] <= 0)
        )
    ].copy()

    print(f"Unique source rows examined: {len(data):,}")
    print(f"Large positive lines: {len(positive_lines):,}")
    print(f"Large negative/cancellation lines: {len(negative_lines):,}")
    print()

    # Group possible positive lines by date to make matching faster.
    positive_by_date = {
        date: group
        for date, group in positive_lines.groupby(
            "transaction_date", dropna=False
        )
        if pd.notna(date)
    }

    results = []

    for _, negative in negative_lines.iterrows():
        transaction_date = negative["transaction_date"]
        negative_amount = numeric_value(negative["line_amount"])
        negative_quantity = numeric_value(negative["quantity"])

        possible_sales = positive_by_date.get(
            transaction_date,
            positive_lines.iloc[0:0],
        )

        # Match on date and absolute amount. Product and quantity
        # are evaluated separately because real adjustments may differ.
        amount_matches = possible_sales[
            (
                possible_sales["line_amount"]
                + negative_amount
            ).abs() <= AMOUNT_TOLERANCE
        ].copy()

        if amount_matches.empty:
            results.append({
                "negative_row_id": negative["row_id"],
                "negative_invoice": negative["invoice_no"],
                "negative_product": negative["stock_code"],
                "negative_quantity": negative["quantity"],
                "negative_unit_price": negative["unit_price"],
                "negative_line_value": negative_amount,
                "transaction_date": transaction_date,
                "negative_description": negative["description"],
                "country": negative["country"],
                "positive_candidate_count": 0,
                "candidate_row_id": None,
                "candidate_invoice": None,
                "candidate_product": None,
                "candidate_quantity": None,
                "candidate_line_value": None,
                "same_product": False,
                "same_absolute_quantity": False,
                "invoice_number_distance": None,
                "review_status": "NO_SAME_DAY_AMOUNT_MATCH",
            })
            continue

        negative_invoice_num = invoice_number(
            negative["invoice_no"]
        )

        ranked_candidates = []

        for _, sale in amount_matches.iterrows():
            same_product = (
                normalize_code(sale["stock_code"])
                == normalize_code(negative["stock_code"])
            )

            same_quantity = (
                abs(
                    abs(numeric_value(sale["quantity"]))
                    - abs(negative_quantity)
                )
                <= QUANTITY_TOLERANCE
            )

            sale_invoice_num = invoice_number(sale["invoice_no"])

            if (
                negative_invoice_num is not None
                and sale_invoice_num is not None
            ):
                invoice_distance = abs(
                    negative_invoice_num - sale_invoice_num
                )
            else:
                invoice_distance = 999999

            # Prefer matching product, then matching quantity,
            # then nearby invoice numbers. This ranks candidates;
            # it does not prove that they are linked.
            score = (
                int(same_product),
                int(same_quantity),
                -invoice_distance,
            )

            ranked_candidates.append(
                (score, sale, same_product, same_quantity,
                 invoice_distance)
            )

        ranked_candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        (
            _,
            best_sale,
            same_product,
            same_quantity,
            invoice_distance,
        ) = ranked_candidates[0]

        candidate_count = len(amount_matches)

        if candidate_count > 1:
            status = "AMBIGUOUS_AMOUNT_MATCH_REVIEW"
        elif same_product and same_quantity:
            status = "STRONG_REVERSAL_CANDIDATE"
        else:
            status = "POSSIBLE_AMOUNT_OFFSET_REVIEW"

        results.append({
            "negative_row_id": negative["row_id"],
            "negative_invoice": negative["invoice_no"],
            "negative_product": negative["stock_code"],
            "negative_quantity": negative["quantity"],
            "negative_unit_price": negative["unit_price"],
            "negative_line_value": negative_amount,
            "transaction_date": transaction_date,
            "negative_description": negative["description"],
            "country": negative["country"],
            "positive_candidate_count": candidate_count,
            "candidate_row_id": best_sale["row_id"],
            "candidate_invoice": best_sale["invoice_no"],
            "candidate_product": best_sale["stock_code"],
            "candidate_quantity": best_sale["quantity"],
            "candidate_line_value": best_sale["line_amount"],
            "same_product": same_product,
            "same_absolute_quantity": same_quantity,
            "invoice_number_distance": invoice_distance,
            "review_status": status,
        })

    report = pd.DataFrame(results)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(OUTPUT_PATH, index=False)

    matched = report[
        report["positive_candidate_count"] > 0
    ]

    strong = report[
        report["review_status"] == "STRONG_REVERSAL_CANDIDATE"
    ]

    ambiguous = report[
        report["review_status"] == "AMBIGUOUS_AMOUNT_MATCH_REVIEW"
    ]

    possible = report[
        report["review_status"] == "POSSIBLE_AMOUNT_OFFSET_REVIEW"
    ]

    unmatched = report[
        report["review_status"] == "NO_SAME_DAY_AMOUNT_MATCH"
    ]

    print("AUDIT SUMMARY")
    print("-" * 52)
    print(f"Negative lines reviewed: {len(report):,}")
    print(f"With same-day amount candidates: {len(matched):,}")
    print(f"Strong reversal candidates: {len(strong):,}")
    print(f"Possible amount offsets: {len(possible):,}")
    print(f"Ambiguous amount matches: {len(ambiguous):,}")
    print(f"No same-day amount match: {len(unmatched):,}")
    print()

    if not matched.empty:
        print("LARGEST MATCHED AMOUNTS")
        print("-" * 52)

        display_columns = [
            "transaction_date",
            "negative_invoice",
            "negative_product",
            "negative_line_value",
            "candidate_invoice",
            "candidate_product",
            "candidate_line_value",
            "same_product",
            "same_absolute_quantity",
            "positive_candidate_count",
            "review_status",
        ]

        largest = matched.reindex(
            matched["negative_line_value"].abs().sort_values(
                ascending=False
            ).index
        ).head(15)

        print(largest[display_columns].to_string(index=False))

    print()
    print(f"Full audit saved to: {OUTPUT_PATH}")
    print()
    print(
        "Important: matching values identify candidates for review. "
        "They do not prove that two records are linked or that "
        "either record is erroneous."
    )


if __name__ == "__main__":
    main()