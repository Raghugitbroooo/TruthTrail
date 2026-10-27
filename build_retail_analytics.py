
import sqlite3
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "data" / "retail_truthtrail.db"
REPORT_DIR = PROJECT_DIR / "reports"


def create_analysis_table(connection):
    print("Preparing an analysis layer without changing raw records...")

    connection.execute("DROP TABLE IF EXISTS retail_analysis_stage")

    connection.execute("""
        CREATE TABLE retail_analysis_stage AS
        SELECT
            row_id,
            invoice_no,
            stock_code,
            description,
            quantity,
            invoice_date,
            unit_price,
            customer_id,
            country,
            is_cancellation_invoice,
            line_amount,

            ROW_NUMBER() OVER (
                PARTITION BY
                    invoice_no,
                    stock_code,
                    description,
                    quantity,
                    invoice_date,
                    unit_price,
                    customer_id,
                    country
                ORDER BY row_id
            ) AS exact_duplicate_rank

        FROM retail_transactions
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_stage_date
        ON retail_analysis_stage(invoice_date)
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_stage_product
        ON retail_analysis_stage(stock_code)
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_stage_country
        ON retail_analysis_stage(country)
    """)


def export_daily_metrics(connection):
    query = """
    SELECT
        SUBSTR(invoice_date, 1, 10) AS date,
        COUNT(*) AS source_rows,
        COUNT(DISTINCT invoice_no) AS invoice_count,

        SUM(
            CASE
                WHEN is_cancellation_invoice = 0
                 AND quantity > 0
                 AND unit_price >= 0
                THEN line_amount
                ELSE 0
            END
        ) AS gross_sales_raw_gbp,

        SUM(
            CASE
                WHEN exact_duplicate_rank = 1
                 AND is_cancellation_invoice = 0
                 AND quantity > 0
                 AND unit_price >= 0
                THEN line_amount
                ELSE 0
            END
        ) AS gross_sales_after_exact_duplicate_exclusion_gbp,

        SUM(
            CASE
                WHEN is_cancellation_invoice = 1
                THEN line_amount
                ELSE 0
            END
        ) AS cancellation_value_raw_gbp,

        SUM(
            CASE
                WHEN exact_duplicate_rank = 1
                 AND is_cancellation_invoice = 1
                THEN line_amount
                ELSE 0
            END
        ) AS cancellation_value_after_exact_duplicate_exclusion_gbp,

        SUM(
            CASE
                WHEN is_cancellation_invoice = 0
                 AND quantity < 0
                THEN line_amount
                ELSE 0
            END
        ) AS negative_quantity_value_raw_gbp,

        SUM(
            CASE
                WHEN exact_duplicate_rank = 1
                 AND is_cancellation_invoice = 0
                 AND quantity < 0
                THEN line_amount
                ELSE 0
            END
        ) AS negative_quantity_value_after_exact_duplicate_exclusion_gbp,

        SUM(
            CASE
                WHEN exact_duplicate_rank > 1 THEN 1
                ELSE 0
            END
        ) AS exact_duplicate_extra_rows,

        SUM(
            CASE
                WHEN unit_price < 0 THEN 1
                ELSE 0
            END
        ) AS negative_price_rows,

        SUM(line_amount) AS raw_net_line_value_gbp,

        SUM(
            CASE
                WHEN exact_duplicate_rank = 1
                THEN line_amount
                ELSE 0
            END
        ) AS net_value_after_exact_duplicate_exclusion_gbp

    FROM retail_analysis_stage
    WHERE invoice_date IS NOT NULL
    GROUP BY SUBSTR(invoice_date, 1, 10)
    ORDER BY date
    """

    return pd.read_sql_query(query, connection)


def export_product_summary(connection):
    query = """
    SELECT
        stock_code,
        MAX(description) AS product_description,
        COUNT(*) AS line_count,
        COUNT(DISTINCT invoice_no) AS invoice_count,
        SUM(quantity) AS units_sold,
        SUM(line_amount) AS gross_sales_gbp

    FROM retail_analysis_stage

    WHERE exact_duplicate_rank = 1
      AND is_cancellation_invoice = 0
      AND quantity > 0
      AND unit_price >= 0

    GROUP BY stock_code
    ORDER BY gross_sales_gbp DESC
    LIMIT 100
    """

    return pd.read_sql_query(query, connection)


def export_country_summary(connection):
    query = """
    SELECT
        country,
        COUNT(*) AS line_count,
        COUNT(DISTINCT invoice_no) AS invoice_count,
        COUNT(DISTINCT customer_id) AS customer_count,
        SUM(quantity) AS units_sold,
        SUM(line_amount) AS gross_sales_gbp

    FROM retail_analysis_stage

    WHERE exact_duplicate_rank = 1
      AND is_cancellation_invoice = 0
      AND quantity > 0
      AND unit_price >= 0

    GROUP BY country
    ORDER BY gross_sales_gbp DESC
    """

    return pd.read_sql_query(query, connection)


def export_quality_summary(connection):
    query = """
    SELECT 'Total transaction lines' AS metric,
           COUNT(*) AS record_count
    FROM retail_analysis_stage

    UNION ALL

    SELECT 'Missing customer IDs', COUNT(*)
    FROM retail_analysis_stage
    WHERE customer_id IS NULL OR TRIM(customer_id) = ''

    UNION ALL

    SELECT 'Missing descriptions', COUNT(*)
    FROM retail_analysis_stage
    WHERE description IS NULL OR TRIM(description) = ''

    UNION ALL

    SELECT 'Extra exact-duplicate rows', COUNT(*)
    FROM retail_analysis_stage
    WHERE exact_duplicate_rank > 1

    UNION ALL

    SELECT 'Cancellation invoice rows', COUNT(*)
    FROM retail_analysis_stage
    WHERE is_cancellation_invoice = 1

    UNION ALL

    SELECT 'Non-positive quantities', COUNT(*)
    FROM retail_analysis_stage
    WHERE quantity <= 0

    UNION ALL

    SELECT 'Negative unit prices', COUNT(*)
    FROM retail_analysis_stage
    WHERE unit_price < 0
    """

    return pd.read_sql_query(query, connection)


def main():
    if not DB_FILE.exists():
        raise FileNotFoundError(
            f"Retail database not found: {DB_FILE}"
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("TruthTrail - Retail Analytics Builder")
    print("=" * 45)

    with sqlite3.connect(DB_FILE) as connection:
        raw_count = connection.execute(
            "SELECT COUNT(*) FROM retail_transactions"
        ).fetchone()[0]

        create_analysis_table(connection)

        stage_count = connection.execute(
            "SELECT COUNT(*) FROM retail_analysis_stage"
        ).fetchone()[0]

        if raw_count != stage_count:
            raise RuntimeError(
                "Analysis stage row count does not match raw data."
            )

        print(f"Raw records preserved: {raw_count:,}")
        print(f"Analysis records created: {stage_count:,}")

        daily = export_daily_metrics(connection)
        products = export_product_summary(connection)
        countries = export_country_summary(connection)
        quality = export_quality_summary(connection)

        daily.to_csv(
            REPORT_DIR / "retail_daily_metrics.csv",
            index=False,
        )
        products.to_csv(
            REPORT_DIR / "retail_product_summary.csv",
            index=False,
        )
        countries.to_csv(
            REPORT_DIR / "retail_country_summary.csv",
            index=False,
        )
        quality.to_csv(
            REPORT_DIR / "retail_quality_summary.csv",
            index=False,
        )

    print("\nAnalytics exports created:")
    print(f"Daily metrics: {len(daily):,} dates")
    print(f"Product summary: {len(products):,} products")
    print(f"Country summary: {len(countries):,} countries")
    print(f"Quality metrics: {len(quality):,} checks")

    print(f"\nReports saved in: {REPORT_DIR}")
    print("Original transaction rows were not deleted.")


if __name__ == "__main__":
    main()
