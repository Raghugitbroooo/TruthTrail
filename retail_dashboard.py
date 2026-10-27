from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st


# ============================================================
# 1. CONFIGURATION
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
REPORT_DIR = PROJECT_DIR / "reports"
DB_FILE = DATA_DIR / "retail_truthtrail.db"

DAILY_FILE = REPORT_DIR / "retail_daily_metrics.csv"
PRODUCT_FILE = REPORT_DIR / "retail_product_summary.csv"
COUNTRY_FILE = REPORT_DIR / "retail_country_summary.csv"
QUALITY_FILE = REPORT_DIR / "retail_quality_summary.csv"
ANOMALY_FILE = REPORT_DIR / "retail_anomaly_findings.csv"
DUAL_ANOMALY_FILE = REPORT_DIR / "retail_dual_metric_anomalies.csv"
GROSS_NET_FILE = REPORT_DIR / "retail_daily_gross_net_metrics.csv"
REVERSAL_FILE = REPORT_DIR / "retail_reversal_reconciliation.csv"
SUSPICIOUS_LINES_FILE = REPORT_DIR / "retail_suspicious_transaction_lines.csv"

SALES_COLUMN = "gross_sales_after_exact_duplicate_exclusion_gbp"
CLASSIFICATIONS_NOT_ALERTS = {"NO_ANOMALY", "INSUFFICIENT_HISTORY"}

st.set_page_config(
    page_title="TruthTrail | Retail Intelligence",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# 2. LOADING / DISPLAY HELPERS
# ============================================================

@st.cache_data(show_spinner=False)
def _read_csv_cached(path_string, modified_ns):
    # modification timestamp is part of the cache key, so regenerated
    # report files will be reloaded rather than staying stale in cache.
    return pd.read_csv(path_string, low_memory=False)


def read_csv(path):
    return _read_csv_cached(str(path), path.stat().st_mtime_ns)


def read_optional_csv(path):
    if not path.exists():
        return pd.DataFrame()
    try:
        return read_csv(path)
    except (pd.errors.ParserError, UnicodeDecodeError, OSError):
        return pd.DataFrame()


def require_file(path):
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")


def money(value):
    try:
        if pd.isna(value):
            return "—"
        return f"£{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def compact_money(value):
    """Format currency compactly so KPI values fit in narrow columns."""
    try:
        if pd.isna(value):
            return "—"
        number = float(value)
        sign = "-" if number < 0 else ""
        magnitude = abs(number)
        if magnitude >= 1_000_000_000:
            return f"{sign}£{magnitude / 1_000_000_000:.2f}B"
        if magnitude >= 1_000_000:
            return f"{sign}£{magnitude / 1_000_000:.2f}M"
        if magnitude >= 10_000:
            return f"{sign}£{magnitude / 1_000:.1f}K"
        if magnitude >= 1_000:
            return f"{sign}£{magnitude / 1_000:.2f}K"
        return f"{sign}£{magnitude:,.2f}"
    except (TypeError, ValueError):
        return "—"


def percent(value, signed=False):
    try:
        if pd.isna(value):
            return "—"
        return f"{float(value):{ '+' if signed else ''}.2f}%"
    except (TypeError, ValueError):
        return "—"


def bool_series(series):
    """Convert CSV bools / strings / numeric flags into actual booleans."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes", "y"})
    )


def add_transaction_review_flags(frame):
    """Add transparent, rule-based review labels to transaction lines."""
    if frame.empty:
        frame = frame.copy()
        frame["review_flags"] = pd.Series(dtype=str)
        return frame

    result = frame.copy()
    for column in ["quantity", "unit_price", "line_amount", "exact_duplicate_rank"]:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")

    if "is_cancellation_invoice" in result.columns:
        result["is_cancellation_invoice"] = pd.to_numeric(
            result["is_cancellation_invoice"], errors="coerce"
        ).fillna(0).astype(int)

    result["review_flags"] = ""
    rules = []

    if "is_cancellation_invoice" in result.columns:
        rules.append((result["is_cancellation_invoice"].eq(1), "CANCELLATION_INVOICE"))
    if "quantity" in result.columns:
        rules.append((result["quantity"].le(0), "NON_POSITIVE_QUANTITY"))
        rules.append((result["quantity"].abs().ge(1000), "HIGH_QUANTITY_REVIEW"))
    if "unit_price" in result.columns:
        rules.append((result["unit_price"].lt(0), "NEGATIVE_UNIT_PRICE"))
    if "line_amount" in result.columns:
        rules.append((result["line_amount"].abs().ge(10000), "HIGH_LINE_VALUE_REVIEW"))
    if "customer_id" in result.columns:
        missing_customer = result["customer_id"].isna() | (
            result["customer_id"].astype(str).str.strip().isin({"", "nan", "None"})
        )
        rules.append((missing_customer, "MISSING_CUSTOMER_ID"))
    if "exact_duplicate_rank" in result.columns:
        rules.append((result["exact_duplicate_rank"].gt(1), "EXACT_DUPLICATE_CANDIDATE"))

    for mask, label in rules:
        result.loc[mask.fillna(False), "review_flags"] = result.loc[
            mask.fillna(False), "review_flags"
        ].apply(lambda current: f"{current}; " if current else "") + label

    result["review_flags"] = result["review_flags"].replace("", "NO_RULE_BASED_FLAG")
    return result


def style_anomaly_table(frame):
    """Show only supported evidence columns when available."""
    desired = [
        "transaction_date",
        "gross_positive_sales",
        "net_transaction_line_value",
        "gross_change_percent",
        "net_change_percent",
        "gross_robust_z",
        "net_robust_z",
        "negative_adjustment_share_pct",
        "classification",
    ]
    return [column for column in desired if column in frame.columns]


def format_classification(value):
    return str(value).replace("_", " ").title()


# ============================================================
# 3. LOAD PROJECT DATA
# ============================================================

st.title("🔎 TruthTrail")
st.subheader("Retail Intelligence & Anomaly Investigation")
st.caption(
    "UCI Online Retail dataset · 541,909 source transaction lines · "
    "SQL-backed quality checks and robust anomaly detection"
)

try:
    for required in [DB_FILE, DAILY_FILE, PRODUCT_FILE, COUNTRY_FILE, QUALITY_FILE, ANOMALY_FILE]:
        require_file(required)

    daily = read_csv(DAILY_FILE)
    products = read_csv(PRODUCT_FILE)
    countries = read_csv(COUNTRY_FILE)
    quality = read_csv(QUALITY_FILE)
    anomalies = read_csv(ANOMALY_FILE)

except (FileNotFoundError, pd.errors.ParserError, OSError) as error:
    st.error(f"Could not load required TruthTrail analytics: {error}")
    st.info(
        "From the project folder, generate the required data in this order:\n\n"
        "1. `python load_retail_database.py` (only if the retail database is missing)\n"
        "2. `python build_retail_analytics.py`\n"
        "3. `python detect_retail_anomalies.py`"
    )
    st.stop()

# New outputs are optional so the dashboard remains usable if a user has
# not generated the later-stage investigation reports yet.
dual = read_optional_csv(DUAL_ANOMALY_FILE)
gross_net_daily = read_optional_csv(GROSS_NET_FILE)
reversals = read_optional_csv(REVERSAL_FILE)
suspicious_lines_report = read_optional_csv(SUSPICIOUS_LINES_FILE)

# Normalize the legacy analytics exports.
if "date" in daily.columns:
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
if "date" in anomalies.columns:
    anomalies["date"] = pd.to_datetime(anomalies["date"], errors="coerce")

for column in [SALES_COLUMN]:
    if column in daily.columns:
        daily[column] = pd.to_numeric(daily[column], errors="coerce")

for column in ["gross_sales_gbp", "baseline_median_gbp", "change_from_baseline_pct", "robust_z_score"]:
    if column in anomalies.columns:
        anomalies[column] = pd.to_numeric(anomalies[column], errors="coerce")

for column in ["gross_sales_gbp"]:
    if column in products.columns:
        products[column] = pd.to_numeric(products[column], errors="coerce")
    if column in countries.columns:
        countries[column] = pd.to_numeric(countries[column], errors="coerce")

# Standardize dual-metric outputs produced by detect_gross_net_anomalies.py.
if not dual.empty:
    if "transaction_date" in dual.columns:
        dual["transaction_date"] = pd.to_datetime(
            dual["transaction_date"], errors="coerce"
        )
        dual["date_only"] = dual["transaction_date"].dt.date

    numeric_dual_columns = [
        "gross_positive_sales",
        "net_transaction_line_value",
        "returns_cancellations_value",
        "cancellation_invoice_value",
        "negative_quantity_value",
        "gross_baseline_median",
        "net_baseline_median",
        "gross_baseline_mad",
        "net_baseline_mad",
        "gross_robust_z",
        "net_robust_z",
        "gross_change_percent",
        "net_change_percent",
        "negative_adjustment_ratio",
        "gross_history_count",
        "net_history_count",
    ]
    for column in numeric_dual_columns:
        if column in dual.columns:
            dual[column] = pd.to_numeric(dual[column], errors="coerce")

    for column in ["gross_is_anomaly", "net_is_anomaly"]:
        if column in dual.columns:
            dual[column] = bool_series(dual[column])
        else:
            dual[column] = False

    if "classification" not in dual.columns:
        dual["classification"] = "UNCLASSIFIED"
    dual = dual.dropna(subset=["transaction_date"]).sort_values("transaction_date")

if not gross_net_daily.empty:
    if "transaction_date" in gross_net_daily.columns:
        gross_net_daily["transaction_date"] = pd.to_datetime(
            gross_net_daily["transaction_date"], errors="coerce"
        )
        gross_net_daily["date_only"] = gross_net_daily["transaction_date"].dt.date
    for column in [
        "gross_positive_sales", "net_transaction_line_value",
        "returns_cancellations_value", "cancellation_invoice_value",
        "negative_quantity_value",
    ]:
        if column in gross_net_daily.columns:
            gross_net_daily[column] = pd.to_numeric(
                gross_net_daily[column], errors="coerce"
            )
    gross_net_daily = gross_net_daily.dropna(subset=["transaction_date"]).sort_values(
        "transaction_date"
    )

if not reversals.empty and "transaction_date" in reversals.columns:
    reversals["transaction_date"] = pd.to_datetime(
        reversals["transaction_date"], errors="coerce"
    )
    reversals["date_only"] = reversals["transaction_date"].dt.strftime("%Y-%m-%d")
    for column in ["negative_line_value", "candidate_line_value"]:
        if column in reversals.columns:
            reversals[column] = pd.to_numeric(reversals[column], errors="coerce")

# Ensure downstream date filtering uses Python date objects consistently.
daily = daily.dropna(subset=["date"]).sort_values("date")
if daily.empty:
    st.error("No valid daily metrics are available.")
    st.stop()
daily["date_only"] = daily["date"].dt.date

anomalies = anomalies.dropna(subset=["date"])
anomalies["date_only"] = anomalies["date"].dt.date

if "metric" in quality.columns and "record_count" in quality.columns:
    total_rows_series = quality.loc[
        quality["metric"].astype(str).str.strip().eq("Total transaction lines"),
        "record_count",
    ]
    total_rows = (
        int(pd.to_numeric(total_rows_series, errors="coerce").dropna().iloc[0])
        if not pd.to_numeric(total_rows_series, errors="coerce").dropna().empty
        else 0
    )
else:
    total_rows = 0

min_date = daily["date_only"].min()
max_date = daily["date_only"].max()


# ============================================================
# 4. FILTERS AND TOP-LEVEL METRICS
# ============================================================

with st.sidebar:
    st.header("TruthTrail Controls")
    st.write("**Database:** SQLite")
    st.write(f"**Source records:** {total_rows:,}")
    st.write("**Anomaly method:** Same-weekday median + MAD")
    st.write("**Detection threshold:** Robust z-score ≥ 3.5")
    st.write("**Local AI:** Optional; not required for analytics")
    st.caption(
        "The dashboard uses deterministic Python/SQL evidence. "
        "An anomaly is a review candidate, not proof of an error."
    )

    selected_range = st.date_input(
        "Analysis date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

if not isinstance(selected_range, (tuple, list)) or len(selected_range) != 2:
    st.info("Select a start date and an end date.")
    st.stop()

start_date, end_date = selected_range
if start_date > end_date:
    st.error("Start date must not be after end date.")
    st.stop()

filtered_daily = daily[
    daily["date_only"].between(start_date, end_date)
].copy()
filtered_anomalies = anomalies[
    anomalies["date_only"].between(start_date, end_date)
].copy()

if "status" in filtered_anomalies.columns:
    potential_anomalies = filtered_anomalies[
        filtered_anomalies["status"].astype(str).eq("Potential anomaly")
    ].copy()
else:
    potential_anomalies = filtered_anomalies.copy()

filtered_dual = pd.DataFrame()
if not dual.empty:
    filtered_dual = dual[dual["date_only"].between(start_date, end_date)].copy()

filtered_reversals = pd.DataFrame()
if not reversals.empty:
    filtered_reversals = reversals[
        reversals["transaction_date"].dt.date.between(start_date, end_date)
    ].copy()

period_sales = pd.to_numeric(
    filtered_daily.get(SALES_COLUMN, pd.Series(dtype=float)), errors="coerce"
).fillna(0).sum()
trading_days = len(filtered_daily)

if not filtered_dual.empty:
    dual_alerts = filtered_dual[
        ~filtered_dual["classification"].isin(CLASSIFICATIONS_NOT_ALERTS)
    ].copy()
    anomaly_count = len(dual_alerts)
    period_net = pd.to_numeric(
        filtered_dual.get("net_transaction_line_value", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0).sum()
    gross_anomaly_count = int(filtered_dual["gross_is_anomaly"].sum())
    net_anomaly_count = int(filtered_dual["net_is_anomaly"].sum())
else:
    dual_alerts = pd.DataFrame()
    anomaly_count = len(potential_anomalies)
    period_net = float("nan")
    gross_anomaly_count = anomaly_count
    net_anomaly_count = 0

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("Source transaction lines", f"{total_rows:,}")
kpi2.metric("Dates in selected range", f"{trading_days:,}")
kpi3.metric("Gross sales (GBP)", compact_money(period_sales))
kpi4.metric("Net line value (GBP)", compact_money(period_net))
kpi5.metric("Potential anomaly dates", f"{anomaly_count:,}")

st.caption(
    f"Selected-range totals at full precision — gross sales: {money(period_sales)}; "
    f"net transaction-line value: {money(period_net)}. "
    "Gross sales exclude cancellation invoices, non-positive quantities, negative prices, "
    "and extra exact-duplicate candidates under the current rules. Net transaction-line "
    "value includes eligible signed transaction lines after extra exact-duplicate exclusion. "
    "Neither measure is audited accounting revenue or profit."
)


# ============================================================
# 5. DASHBOARD TABS
# ============================================================

overview_tab, anomaly_tab, market_tab, quality_tab, explore_tab, investigation_tab = st.tabs([
    "📊 Overview",
    "🚨 Anomalies",
    "🌍 Products & Countries",
    "🛡️ Data Quality",
    "🔎 Explore Records",
    "🧭 Investigation Evidence",
])


# ============================================================
# 6. OVERVIEW
# ============================================================

with overview_tab:
    st.subheader("Daily Sales: Gross vs Net Transaction-Line Value")

    if filtered_daily.empty:
        st.info("No daily metrics exist for this date range.")
    else:
        metric_source = filtered_dual.copy() if not filtered_dual.empty else pd.DataFrame()
        if metric_source.empty and not gross_net_daily.empty:
            metric_source = gross_net_daily[
                gross_net_daily["date_only"].between(start_date, end_date)
            ].copy()

        if not metric_source.empty and {
            "gross_positive_sales", "net_transaction_line_value"
        }.issubset(metric_source.columns):
            chart = metric_source.set_index("transaction_date")[
                ["gross_positive_sales", "net_transaction_line_value"]
            ].rename(columns={
                "gross_positive_sales": "Gross positive sales",
                "net_transaction_line_value": "Net transaction-line value",
            })
            st.line_chart(chart)
            st.caption(
                "Gross positive sales and signed net transaction-line value are shown separately. "
                "A large difference may reflect returns, cancellations, or other negative lines."
            )
        else:
            chart = filtered_daily.set_index("date")[[SALES_COLUMN]].rename(
                columns={SALES_COLUMN: "Gross sales (GBP)"}
            )
            st.line_chart(chart)
            st.info(
                "Generate `retail_dual_metric_anomalies.csv` to enable the gross-vs-net view."
            )

        st.subheader("Daily Metrics")
        display_columns = [
            column for column in [
                "date", "source_rows", "invoice_count", "gross_sales_raw_gbp",
                SALES_COLUMN, "cancellation_value_raw_gbp", "exact_duplicate_extra_rows",
            ] if column in filtered_daily.columns
        ]
        st.dataframe(
            filtered_daily[display_columns],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("How to read TruthTrail alerts")
    st.markdown(
        "- **Gross and net anomaly:** sales remain unusual after negative transaction values are included.\n"
        "- **Gross spike mostly offset:** gross sales are unusually high, but signed transaction values are much lower.\n"
        "- **Net-only anomaly:** net transaction-line value is unusual even though gross sales are not flagged.\n"
        "- **Insufficient history:** the detector has not yet collected enough same-weekday observations."
    )


# ============================================================
# 7. ANOMALY DETECTION AND COMPARISON
# ============================================================

with anomaly_tab:
    st.subheader("Dual-Metric Anomaly Detection")

    if not filtered_dual.empty:
        alert_classes = sorted(
            value for value in filtered_dual["classification"].dropna().astype(str).unique()
            if value not in CLASSIFICATIONS_NOT_ALERTS
        )
        selected_classes = st.multiselect(
            "Filter alert classifications",
            options=alert_classes,
            default=alert_classes,
            format_func=format_classification,
        )
        visible_alerts = filtered_dual[
            filtered_dual["classification"].isin(selected_classes)
        ].copy()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Gross anomalies", f"{gross_anomaly_count:,}")
        c2.metric("Net anomalies", f"{net_anomaly_count:,}")
        c3.metric("Dates flagged by either metric", f"{anomaly_count:,}")
        c4.metric(
            "Gross spikes mostly offset",
            f"{int(filtered_dual['classification'].eq('GROSS_SPIKE_MOSTLY_OFFSET').sum()):,}",
        )

        chart_columns = [
            column for column in [
                "gross_positive_sales", "gross_baseline_median",
                "net_transaction_line_value", "net_baseline_median",
            ] if column in filtered_dual.columns
        ]
        if chart_columns:
            chart = filtered_dual.set_index("transaction_date")[chart_columns].rename(
                columns={
                    "gross_positive_sales": "Gross actual",
                    "gross_baseline_median": "Gross baseline median",
                    "net_transaction_line_value": "Net actual",
                    "net_baseline_median": "Net baseline median",
                }
            )
            st.line_chart(chart)

        if visible_alerts.empty:
            st.info("No alerts match the selected classifications and date range.")
        else:
            visible_alerts["negative_adjustment_share_pct"] = (
                pd.to_numeric(
                    visible_alerts.get("negative_adjustment_ratio", pd.Series(index=visible_alerts.index, dtype=float)),
                    errors="coerce",
                ) * 100
            )
            display_columns = style_anomaly_table(visible_alerts)
            display = visible_alerts[display_columns].copy()
            if "transaction_date" in display.columns:
                display["transaction_date"] = pd.to_datetime(
                    display["transaction_date"], errors="coerce"
                ).dt.strftime("%Y-%m-%d")
            st.dataframe(
                display.sort_values("transaction_date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "Download dual-metric anomaly results",
                data=visible_alerts.drop(columns=["date_only"], errors="ignore").to_csv(index=False),
                file_name="truthtrail_dual_metric_anomalies.csv",
                mime="text/csv",
            )

        with st.expander("Compare with the original gross-only detector"):
            st.caption(
                "This legacy detector uses its original gross-sales rules. Its findings are kept "
                "for comparison and are not silently combined with the dual-metric classifications."
            )
            if potential_anomalies.empty:
                st.info("No legacy gross-only anomaly rows in this selected period.")
            else:
                baseline_columns = [
                    column for column in [
                        "date", "weekday", "gross_sales_gbp", "historical_observations",
                        "baseline_median_gbp", "change_from_baseline_pct", "robust_z_score",
                        "detection_method", "status",
                    ] if column in potential_anomalies.columns
                ]
                st.dataframe(
                    potential_anomalies[baseline_columns].sort_values("date", ascending=False),
                    use_container_width=True,
                    hide_index=True,
                )
                st.download_button(
                    "Download original gross-only findings",
                    data=potential_anomalies[baseline_columns].to_csv(index=False),
                    file_name="truthtrail_gross_only_findings.csv",
                    mime="text/csv",
                )
    else:
        st.warning(
            "The dual-metric report has not been generated yet. The original gross-only detector remains available below."
        )
        if potential_anomalies.empty:
            st.info("No potential anomalies were flagged in this date range.")
        else:
            legacy_columns = [
                column for column in [
                    "date", "weekday", "gross_sales_gbp", "historical_observations",
                    "baseline_median_gbp", "change_from_baseline_pct", "robust_z_score",
                    "detection_method", "status",
                ] if column in potential_anomalies.columns
            ]
            st.dataframe(
                potential_anomalies[legacy_columns].sort_values("date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

    st.warning(
        "An anomaly is a candidate for review, not proof of an error. "
        "The thresholds are exploratory and have not been validated against a labelled ground-truth dataset."
    )


# ============================================================
# 8. PRODUCT AND COUNTRY ANALYTICS
# ============================================================

with market_tab:
    product_col, country_col = st.columns(2)

    with product_col:
        st.subheader("Top Products by Gross Sales")
        if {"gross_sales_gbp", "stock_code", "product_description"}.issubset(products.columns):
            top_products = products.nlargest(15, "gross_sales_gbp").sort_values("gross_sales_gbp")
            top_products["product_label"] = (
                top_products["stock_code"].astype(str)
                + " — "
                + top_products["product_description"].fillna("(no description)").astype(str).str.slice(0, 35)
            )
            product_chart = top_products.set_index("product_label")[["gross_sales_gbp"]].rename(
                columns={"gross_sales_gbp": "Gross sales (GBP)"}
            )
            st.bar_chart(product_chart)
            display_columns = [
                column for column in [
                    "stock_code", "product_description", "line_count", "invoice_count",
                    "units_sold", "gross_sales_gbp",
                ] if column in products.columns
            ]
            st.dataframe(
                products.nlargest(15, "gross_sales_gbp")[display_columns],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("The product summary is missing expected columns.")

    with country_col:
        st.subheader("Sales by Country")
        if {"gross_sales_gbp", "country"}.issubset(countries.columns):
            top_countries = countries.nlargest(12, "gross_sales_gbp").sort_values("gross_sales_gbp")
            country_chart = top_countries.set_index("country")[["gross_sales_gbp"]].rename(
                columns={"gross_sales_gbp": "Gross sales (GBP)"}
            )
            st.bar_chart(country_chart)
            display_columns = [
                column for column in [
                    "country", "line_count", "invoice_count", "customer_count",
                    "units_sold", "gross_sales_gbp",
                ] if column in countries.columns
            ]
            st.dataframe(
                countries.nlargest(12, "gross_sales_gbp")[display_columns],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("The country summary is missing expected columns.")

    st.caption(
        "Product and country summaries show the full dataset rather than only the selected date range. "
        "Their definitions follow the analytics builder."
    )


# ============================================================
# 9. DATA QUALITY AND REVERSAL RECONCILIATION
# ============================================================

with quality_tab:
    st.subheader("Retail Data Quality Profile")
    st.dataframe(quality, use_container_width=True, hide_index=True)

    st.markdown("### Interpretation guide")
    st.markdown(
        "- Missing customer IDs limit customer-level analysis but do not automatically invalidate a transaction.\n"
        "- Repeated invoice numbers can represent legitimate multi-product invoices.\n"
        "- Cancellation invoices and negative quantities need separate business rules.\n"
        "- Exact duplicate candidates are excluded from certain derived metrics, but remain in the source database.\n"
        "- Rule-based flags identify records to inspect; they do not delete or correct source data."
    )

    if not reversals.empty:
        st.divider()
        st.subheader("Large-Value Same-Day Reversal Candidates")
        st.caption(
            "This audit only examines negative/cancellation lines meeting the £1,000 threshold. "
            "A match means the date and absolute value agree within tolerance; product, quantity, "
            "and candidate uniqueness affect the review status."
        )

        if "review_status" in reversals.columns:
            strong_count = int(reversals["review_status"].eq("STRONG_REVERSAL_CANDIDATE").sum())
            possible_count = int(reversals["review_status"].eq("POSSIBLE_AMOUNT_OFFSET_REVIEW").sum())
            ambiguous_count = int(reversals["review_status"].eq("AMBIGUOUS_AMOUNT_MATCH_REVIEW").sum())
            matched_count = int(
                pd.to_numeric(
                    reversals.get("positive_candidate_count", pd.Series(0, index=reversals.index)),
                    errors="coerce",
                ).fillna(0).gt(0).sum()
            )
            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.metric("Negative lines reviewed", f"{len(reversals):,}")
            rc2.metric("Same-day amount matches", f"{matched_count:,}")
            rc3.metric("Strong candidates", f"{strong_count:,}")
            rc4.metric("Ambiguous candidates", f"{ambiguous_count:,}")

            preferred = [
                column for column in [
                    "transaction_date", "negative_invoice", "negative_product",
                    "negative_line_value", "candidate_invoice", "candidate_product",
                    "candidate_line_value", "same_product", "same_absolute_quantity",
                    "positive_candidate_count", "review_status",
                ] if column in reversals.columns
            ]
            if preferred:
                top_reversals = reversals.copy()
                if "negative_line_value" in top_reversals.columns:
                    top_reversals["abs_value"] = top_reversals["negative_line_value"].abs()
                    top_reversals = top_reversals.sort_values("abs_value", ascending=False)
                st.dataframe(
                    top_reversals[preferred].head(25),
                    use_container_width=True,
                    hide_index=True,
                )
                st.download_button(
                    "Download reversal reconciliation audit",
                    data=reversals.drop(columns=["date_only"], errors="ignore").to_csv(index=False),
                    file_name="truthtrail_reversal_reconciliation.csv",
                    mime="text/csv",
                )
            st.warning(
                "The heuristic can assign the same positive invoice line to more than one negative line. "
                "These are candidate relationships, not confirmed one-to-one reversal pairs."
            )
    else:
        st.info(
            "Optional reversal reconciliation report not found. The rest of the dashboard is unaffected. "
            "Generate `retail_reversal_reconciliation.csv` to display it here."
        )


# ============================================================
# 10. TRANSACTION SEARCH
# ============================================================

with explore_tab:
    st.subheader("Explore Retail Transactions")
    search_text = st.text_input(
        "Search invoice, product, customer, description, or country",
        placeholder="Example: 536365 or United Kingdom",
    )
    result_limit = st.selectbox(
        "Maximum records to display", [100, 250, 500, 1000], index=1
    )
    st.caption("Searches use parameterized SQL and are limited to keep the dashboard responsive.")

    if st.button("Search retail database", key="search_retail_database"):
        query = """
        SELECT
            row_id, invoice_no, stock_code, description, quantity,
            invoice_date, unit_price, customer_id, country,
            is_cancellation_invoice, line_amount
        FROM retail_transactions
        WHERE invoice_date >= ?
          AND invoice_date < ?
          AND (
              invoice_no LIKE ?
              OR stock_code LIKE ?
              OR description LIKE ?
              OR CAST(customer_id AS TEXT) LIKE ?
              OR country LIKE ?
          )
        ORDER BY invoice_date DESC, row_id DESC
        LIMIT ?
        """
        search_pattern = f"%{search_text.strip()}%"
        start_boundary = f"{start_date} 00:00:00"
        end_boundary = f"{pd.Timestamp(end_date) + pd.Timedelta(days=1)} 00:00:00"

        try:
            with sqlite3.connect(DB_FILE) as connection:
                results = pd.read_sql_query(
                    query,
                    connection,
                    params=[
                        start_boundary, end_boundary,
                        search_pattern, search_pattern, search_pattern,
                        search_pattern, search_pattern, result_limit,
                    ],
                )
            st.write(f"Records returned: {len(results):,}")
            st.dataframe(results, use_container_width=True, hide_index=True)
            if len(results) == result_limit:
                st.info("Display limit reached. Narrow the search or date range to inspect other matches.")
        except sqlite3.Error as error:
            st.error(f"Database search failed: {error}")


# ============================================================
# 11. INVESTIGATION EVIDENCE
# ============================================================

with investigation_tab:
    st.subheader("Investigate a Flagged Date")
    st.caption(
        "Choose an alert to review daily metrics, top contributing products, and the largest transaction lines. "
        "Evidence is intended to help prioritize a human review."
    )

    if not filtered_dual.empty:
        choices_frame = filtered_dual[
            ~filtered_dual["classification"].isin(CLASSIFICATIONS_NOT_ALERTS)
        ].copy()
        if choices_frame.empty:
            choices_frame = filtered_dual.copy()
        choices_frame["date_label"] = choices_frame["transaction_date"].dt.strftime("%Y-%m-%d")
        choices_frame["strength"] = pd.concat(
            [
                pd.to_numeric(choices_frame.get("gross_robust_z", pd.Series(index=choices_frame.index, dtype=float)), errors="coerce").abs(),
                pd.to_numeric(choices_frame.get("net_robust_z", pd.Series(index=choices_frame.index, dtype=float)), errors="coerce").abs(),
            ], axis=1
        ).max(axis=1)
        choices_frame = choices_frame.sort_values("strength", ascending=False)
        date_options = choices_frame["date_label"].drop_duplicates().tolist()
    else:
        legacy_choices = potential_anomalies.copy()
        if "date" in legacy_choices.columns:
            date_options = legacy_choices["date"].dt.strftime("%Y-%m-%d").dropna().drop_duplicates().tolist()
            date_options = sorted(date_options, reverse=True)
        else:
            date_options = []

    if not date_options:
        st.info(
            "No alert dates are available for the current filter. Widen the date range or generate the dual-metric report."
        )
    else:
        selected_detail_date = st.selectbox(
            "Select an anomaly date",
            date_options,
            index=0,
            key="investigation_date",
        )

        if not filtered_dual.empty:
            matching_daily = filtered_dual[
                filtered_dual["transaction_date"].dt.strftime("%Y-%m-%d").eq(selected_detail_date)
            ]
        else:
            matching_daily = pd.DataFrame()

        if not matching_daily.empty:
            detail = matching_daily.iloc[0]
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Gross positive sales", money(detail.get("gross_positive_sales")))
            d2.metric("Net line value", money(detail.get("net_transaction_line_value")))
            d3.metric("Gross change vs baseline", percent(detail.get("gross_change_percent"), signed=True))
            d4.metric("Net change vs baseline", percent(detail.get("net_change_percent"), signed=True))
            st.markdown(f"**Classification:** `{detail.get('classification', 'UNCLASSIFIED')}`")
            ratio = detail.get("negative_adjustment_ratio")
            if pd.notna(ratio):
                st.write(f"Negative adjustment share: **{float(ratio) * 100:.2f}%**")
            st.caption(
                "Same-weekday historical baselines use up to eight earlier observations and require at least four. "
                "When historical MAD is zero, the detector uses its percentage-change fallback."
            )

        include_duplicates = st.checkbox(
            "Include extra exact-duplicate candidates in the line-level evidence",
            value=False,
            help="Off by default to match the duplicate-exclusion rule used in the daily comparison metrics.",
        )

        evidence_sql = """
        SELECT
            row_id, invoice_no, stock_code, description, quantity,
            invoice_date, unit_price, customer_id, country,
            is_cancellation_invoice, line_amount, exact_duplicate_rank
        FROM retail_analysis_stage
        WHERE date(invoice_date) = ?
          AND (? = 1 OR CAST(exact_duplicate_rank AS INTEGER) = 1)
        ORDER BY ABS(CAST(COALESCE(line_amount, 0) AS REAL)) DESC, row_id
        LIMIT 40
        """
        product_sql = """
        SELECT
            stock_code,
            MAX(description) AS product_description,
            SUM(CASE WHEN CAST(exact_duplicate_rank AS INTEGER) = 1 THEN 1 ELSE 0 END) AS unique_line_count,
            SUM(CASE
                WHEN CAST(exact_duplicate_rank AS INTEGER) = 1
                 AND CAST(COALESCE(is_cancellation_invoice, 0) AS INTEGER) = 0
                 AND CAST(COALESCE(quantity, 0) AS REAL) > 0
                 AND CAST(COALESCE(unit_price, -1) AS REAL) >= 0
                THEN CAST(COALESCE(line_amount, 0) AS REAL) ELSE 0 END
            ) AS gross_positive_sales,
            SUM(CASE
                WHEN CAST(exact_duplicate_rank AS INTEGER) = 1
                 AND CAST(COALESCE(unit_price, -1) AS REAL) >= 0
                THEN CAST(COALESCE(line_amount, 0) AS REAL) ELSE 0 END
            ) AS net_transaction_line_value,
            SUM(CASE
                WHEN CAST(exact_duplicate_rank AS INTEGER) = 1
                 AND (CAST(COALESCE(is_cancellation_invoice, 0) AS INTEGER) = 1
                      OR CAST(COALESCE(quantity, 0) AS REAL) <= 0)
                THEN 1 ELSE 0 END
            ) AS return_or_cancellation_lines
        FROM retail_analysis_stage
        WHERE date(invoice_date) = ?
        GROUP BY stock_code
        ORDER BY ABS(net_transaction_line_value) DESC
        LIMIT 15
        """

        try:
            with sqlite3.connect(DB_FILE) as connection:
                evidence = pd.read_sql_query(
                    evidence_sql,
                    connection,
                    params=[selected_detail_date, int(include_duplicates)],
                )
                product_drivers = pd.read_sql_query(
                    product_sql, connection, params=[selected_detail_date]
                )

            if evidence.empty:
                st.info("No transaction lines found for this date in the analysis table.")
            else:
                evidence = add_transaction_review_flags(evidence)
                st.markdown("### Transaction-level evidence")
                st.caption(
                    "Top 40 lines by absolute line value. Review flags are transparent rules, not definitive error labels."
                )
                evidence_columns = [
                    column for column in [
                        "row_id", "invoice_no", "stock_code", "description", "quantity",
                        "invoice_date", "unit_price", "line_amount", "customer_id", "country",
                        "is_cancellation_invoice", "exact_duplicate_rank", "review_flags",
                    ] if column in evidence.columns
                ]
                st.dataframe(
                    evidence[evidence_columns],
                    use_container_width=True,
                    hide_index=True,
                )
                st.download_button(
                    "Download displayed transaction evidence",
                    data=evidence[evidence_columns].to_csv(index=False),
                    file_name=f"truthtrail_transaction_evidence_{selected_detail_date}.csv",
                    mime="text/csv",
                )

                st.markdown("### Product contribution evidence")
                st.dataframe(
                    product_drivers,
                    use_container_width=True,
                    hide_index=True,
                )

            if not reversals.empty:
                same_day_reversals = reversals[
                    reversals["transaction_date"].dt.strftime("%Y-%m-%d").eq(selected_detail_date)
                ]
                if not same_day_reversals.empty:
                    st.markdown("### Same-day amount-match candidates")
                    rev_columns = [
                        column for column in [
                            "negative_invoice", "negative_product", "negative_quantity",
                            "negative_line_value", "candidate_invoice", "candidate_product",
                            "candidate_quantity", "candidate_line_value", "same_product",
                            "same_absolute_quantity", "positive_candidate_count", "review_status",
                        ] if column in same_day_reversals.columns
                    ]
                    st.dataframe(
                        same_day_reversals[rev_columns],
                        use_container_width=True,
                        hide_index=True,
                    )

        except (sqlite3.Error, pd.errors.DatabaseError) as error:
            st.error(f"Could not retrieve line-level evidence: {error}")
            if not suspicious_lines_report.empty and "transaction_date" in suspicious_lines_report.columns:
                fallback = suspicious_lines_report[
                    suspicious_lines_report["transaction_date"].astype(str).eq(selected_detail_date)
                ]
                if not fallback.empty:
                    st.info("Showing the saved investigation export as a fallback.")
                    st.dataframe(fallback, use_container_width=True, hide_index=True)


# ============================================================
# 12. FOOTER
# ============================================================

st.divider()
st.caption(
    "TruthTrail Retail Intelligence | Python · SQL · SQLite · pandas · Streamlit · "
    "Robust statistics · Evidence-led human review"
)
