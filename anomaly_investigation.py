
import sqlite3
from pathlib import Path


DB_FILE = Path(__file__).resolve().parent / "data" / "truthtrail.db"


def get_product_revenue(connection):
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
        product,
        SUM(
            CAST(quantity AS INTEGER) *
            CAST(unit_price AS REAL)
        ) AS revenue
    FROM accepted
    GROUP BY order_date, product
    ORDER BY order_date, product
    """

    return connection.execute(query).fetchall()


def main():
    if not DB_FILE.exists():
        print("Database not found. Run python load_database.py first.")
        return

    with sqlite3.connect(DB_FILE) as connection:
        rows = get_product_revenue(connection)

    # Store revenue by date and product.
    daily_products = {}

    for order_date, product, revenue in rows:
        product = product or "(unknown)"
        daily_products.setdefault(order_date, {})
        daily_products[order_date][product] = revenue

    dates = sorted(daily_products)

    print("TruthTrail - Anomaly Investigation")
    print("-" * 45)

    if len(dates) < 2:
        print("At least two dates are needed for comparison.")
        return

    for index in range(1, len(dates)):
        previous_date = dates[index - 1]
        current_date = dates[index]

        previous = daily_products[previous_date]
        current = daily_products[current_date]

        previous_total = sum(previous.values())
        current_total = sum(current.values())
        net_change = current_total - previous_total

        print(f"\nComparison: {previous_date} -> {current_date}")
        print(f"Previous revenue: {previous_total:,.2f}")
        print(f"Current revenue:  {current_total:,.2f}")
        print(f"Net change:       {net_change:+,.2f}")

        products = set(previous) | set(current)
        changes = []

        for product in products:
            difference = (
                current.get(product, 0)
                - previous.get(product, 0)
            )

            if difference != 0:
                changes.append((product, difference))

        changes.sort(key=lambda item: abs(item[1]), reverse=True)

        print("Largest product-level changes:")

        for product, difference in changes[:5]:
            print(f"  {product}: {difference:+,.2f}")

        print(
            "Note: These are product-level contributors, "
            "not proof of the underlying cause."
        )


if __name__ == "__main__":
    main()
