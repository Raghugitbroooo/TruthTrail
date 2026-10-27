from pathlib import Path
import sqlite3

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "data" / "retail_truthtrail.db"
OUTPUT_PATH = (
    PROJECT_DIR
    / "reports"
    / "retail_daily_gross_net_metrics.csv"
)

DATES_TO_EXAMINE = [
    "2011-09-20",
    "2011-07-28",
    "2011-12-09",
    "2011-06-10",
    "2011-11-14",
]


def money(value):
    return f"£{value:,.2f}"


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    print("TruthTrail - Gross vs Net Transaction Analysis")
    print("=" * 54)
    print("Reading the retail analysis table...")

    with sqlite3.connect(DB_PATH) as connection:
        data = pd.read_sql_query(
            """
            SELECT
                row_id,
                invoice_no,
                quantity,
                invoice_date,
                unit_price,
                line_amount,
                customer_id,
                is_cancellation_invoice,
                exact_duplicate_rank
            FROM retail_analysis_stage
            """,
            connection,
        )

    source_rows = len(data)

    # Convert fields explicitly so calculations are reliable.
    for column in [
        "quantity",
        "unit_price",
        "line_amount",
        "exact_duplicate_rank",
        "is_cancellation_invoice",
    ]:
        data[column] = pd.to_numeric(
            data[column], errors="coerce"
        )

    data["invoice_date"] = pd.to_datetime(
        data["invoice_date"], errors="coerce"
    )

    data["transaction_date"] = (
        data["invoice_date"].dt.strftime("%Y-%m-%d")
    )

    data["is_cancellation_invoice"] = (
        data["is_cancellation_invoice"]
        .fillna(0)
        .astype(int)
    )

    # Exclude rows whose transaction date cannot be assigned
    # to a calendar day.
    missing_date_rows = int(
        data["transaction_date"].isna().sum()
    )
    data = data[data["transaction_date"].notna()].copy()

    # Keep one representative from each exact-duplicate group.
    # The original rows remain in the database.
    unique_rows = data[
        data["exact_duplicate_rank"] == 1
    ].copy()

    duplicate_extras = data[
        data["exact_duplicate_rank"] > 1
    ].copy()

    # Identify transaction values eligible for the two measures.
    valid_price = (
        unique_rows["unit_price"].notna()
        & (unique_rows["unit_price"] >= 0)
    )

    valid_quantity = unique_rows["quantity"].notna()
    valid_amount = unique_rows["line_amount"].notna()

    # Measure 1: gross positive sales.
    gross_mask = (
        valid_price
        & valid_quantity
        & valid_amount
        & (unique_rows["quantity"] > 0)
        & (unique_rows["is_cancellation_invoice"] == 0)
    )

    unique_rows["gross_positive_sales"] = (
        unique_rows["line_amount"].where(gross_mask, 0)
    )

    # Measure 2: signed transaction-line value.
    # This includes negative quantities and cancellation invoices.
    net_mask = (
        valid_price
        & valid_quantity
        & valid_amount
    )

    unique_rows["net_transaction_line_value"] = (
        unique_rows["line_amount"].where(net_mask, 0)
    )

    # Show the signed effect of rows classified as returns
    # or cancellation invoices.
    adjustment_mask = (
        valid_price
        & valid_quantity
        & valid_amount
        & (
            (unique_rows["is_cancellation_invoice"] == 1)
            | (unique_rows["quantity"] <= 0)
        )
    )

    unique_rows["returns_cancellations_value"] = (
        unique_rows["line_amount"].where(
            adjustment_mask, 0
        )
    )

    cancellation_mask = (
        valid_price
        & valid_quantity
        & valid_amount
        & (unique_rows["is_cancellation_invoice"] == 1)
    )

    unique_rows["cancellation_invoice_value"] = (
        unique_rows["line_amount"].where(
            cancellation_mask, 0
        )
    )

    negative_quantity_mask = (
        valid_price
        & valid_quantity
        & valid_amount
        & (unique_rows["quantity"] < 0)
    )

    unique_rows["negative_quantity_value"] = (
        unique_rows["line_amount"].where(
            negative_quantity_mask, 0
        )
    )

    unique_rows["negative_price_line_count"] = (
        unique_rows["unit_price"].notna()
        & (unique_rows["unit_price"] < 0)
    ).astype(int)

    unique_rows["eligible_gross_line_count"] = (
        gross_mask.astype(int)
    )

    # Aggregate the unique records by date.
    daily = (
        unique_rows.groupby("transaction_date")
        .agg(
            unique_source_lines=("row_id", "count"),
            gross_positive_sales=(
                "gross_positive_sales", "sum"
            ),
            net_transaction_line_value=(
                "net_transaction_line_value", "sum"
            ),
            returns_cancellations_value=(
                "returns_cancellations_value", "sum"
            ),
            cancellation_invoice_value=(
                "cancellation_invoice_value", "sum"
            ),
            negative_quantity_value=(
                "negative_quantity_value", "sum"
            ),
            negative_price_line_count=(
                "negative_price_line_count", "sum"
            ),
            eligible_gross_line_count=(
                "eligible_gross_line_count", "sum"
            ),
        )
        .reset_index()
    )

    # Count extra exact-duplicate rows excluded from the metrics.
    duplicate_counts = (
        duplicate_extras.groupby("transaction_date")
        .size()
        .rename("exact_duplicate_extra_rows_excluded")
        .reset_index()
    )

    daily = daily.merge(
        duplicate_counts,
        on="transaction_date",
        how="left",
    )

    daily["exact_duplicate_extra_rows_excluded"] = (
        daily["exact_duplicate_extra_rows_excluded"]
        .fillna(0)
        .astype(int)
    )

    # A diagnostic difference, not an accounting reconciliation.
    daily["gross_minus_net_value"] = (
        daily["gross_positive_sales"]
        - daily["net_transaction_line_value"]
    )

    daily = daily.sort_values("transaction_date")

    OUTPUT_PATH.parent.mkdir(
        parents=True, exist_ok=True
    )
    daily.to_csv(OUTPUT_PATH, index=False)

    # Totals across the daily report.
    total_gross = daily["gross_positive_sales"].sum()
    total_net = daily[
        "net_transaction_line_value"
    ].sum()
    total_adjustments = daily[
        "returns_cancellations_value"
    ].sum()
    total_cancel_value = daily[
        "cancellation_invoice_value"
    ].sum()
    total_negative_quantity_value = daily[
        "negative_quantity_value"
    ].sum()
    total_duplicates_excluded = daily[
        "exact_duplicate_extra_rows_excluded"
    ].sum()

    print()
    print("DATA SUMMARY")
    print("-" * 54)
    print(f"Source rows read: {source_rows:,}")
    print(f"Unique rows used: {len(unique_rows):,}")
    print(f"Extra exact-duplicate rows excluded: "
          f"{total_duplicates_excluded:,}")
    print(f"Rows without usable dates: {missing_date_rows:,}")
    print(f"Calendar dates analyzed: {len(daily):,}")

    print()
    print("VALUE SUMMARY")
    print("-" * 54)
    print(f"Gross positive sales: {money(total_gross)}")
    print(f"Net transaction-line value: {money(total_net)}")
    print(f"Returns/cancellation line value: "
          f"{money(total_adjustments)}")
    print(f"Cancellation-invoice line value: "
          f"{money(total_cancel_value)}")
    print(f"Negative-quantity line value: "
          f"{money(total_negative_quantity_value)}")

    print()
    print("ANOMALY DATE COMPARISON")
    print("-" * 78)
    print(
        f"{'Date':<13}"
        f"{'Gross sales':>17}"
        f"{'Net line value':>19}"
        f"{'Returns/cancels':>20}"
    )
    print("-" * 78)

    daily_by_date = daily.set_index("transaction_date")

    for date in DATES_TO_EXAMINE:
        if date not in daily_by_date.index:
            print(f"{date:<13} No daily data found")
            continue

        row = daily_by_date.loc[date]

        # A date should correspond to one daily row.
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        print(
            f"{date:<13}"
            f"{money(row['gross_positive_sales']):>17}"
            f"{money(row['net_transaction_line_value']):>19}"
            f"{money(row['returns_cancellations_value']):>20}"
        )

    print()
    print(f"Report saved to: {OUTPUT_PATH}")
    print()
    print(
        "Interpretation note: net transaction-line value is a "
        "data-analysis metric, not audited revenue or profit. "
        "An unusual value is an investigation signal, not proof "
        "of an error."
    )


if __name__ == "__main__":
    main()