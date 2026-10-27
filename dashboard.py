
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st


# ==================================================
# 1. PROJECT CONFIGURATION
# ==================================================

PROJECT_DIR = Path(__file__).resolve().parent

DB_FILE = PROJECT_DIR / "data" / "truthtrail.db"
EVIDENCE_FILE = PROJECT_DIR / "reports" / "incident_evidence.json"
REPORT_FILE = PROJECT_DIR / "reports" / "incident_report.md"
AI_SCRIPT = PROJECT_DIR / "ai_incident_report.py"
LOG_FILE = PROJECT_DIR / "reports" / "ai_generation.log"

ANOMALY_THRESHOLD = 50.0

st.set_page_config(
    page_title="TruthTrail | Data Detective",
    page_icon="🔎",
    layout="wide",
)


# ==================================================
# 2. LOAD DATA FROM SQLITE
# ==================================================

def load_transactions():
    if not DB_FILE.exists():
        raise FileNotFoundError(
            "Database not found. Run python load_database.py first."
        )

    with sqlite3.connect(DB_FILE) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute("""
            SELECT
                row_id,
                transaction_id,
                order_date,
                customer_id,
                product,
                quantity,
                unit_price,
                payment_status
            FROM transactions
            ORDER BY row_id
        """).fetchall()

    return [dict(row) for row in rows]


# ==================================================
# 3. DATA QUALITY AND REVENUE ANALYSIS
# ==================================================

def analyze_transactions(rows):
    seen_ids = set()
    issues = []
    accepted = []

    for row in rows:
        row_id = row["row_id"]
        transaction_id = str(
            row.get("transaction_id") or ""
        ).strip()

        is_duplicate = False

        # Check transaction ID.
        if not transaction_id:
            issues.append({
                "Row ID": row_id,
                "Transaction ID": "(missing)",
                "Issue": "Missing transaction ID",
            })

        elif transaction_id in seen_ids:
            is_duplicate = True
            issues.append({
                "Row ID": row_id,
                "Transaction ID": transaction_id,
                "Issue": "Duplicate transaction ID",
            })

        else:
            seen_ids.add(transaction_id)

        # Check customer ID.
        customer_id = str(
            row.get("customer_id") or ""
        ).strip()

        if not customer_id:
            issues.append({
                "Row ID": row_id,
                "Transaction ID": transaction_id or "(missing)",
                "Issue": "Missing customer ID",
            })

        # Check quantity.
        quantity = None

        try:
            quantity = int(
                str(row.get("quantity") or "").strip()
            )

            if quantity <= 0:
                issues.append({
                    "Row ID": row_id,
                    "Transaction ID": transaction_id,
                    "Issue": "Quantity must be greater than zero",
                })

        except (ValueError, TypeError):
            issues.append({
                "Row ID": row_id,
                "Transaction ID": transaction_id,
                "Issue": "Quantity is missing or invalid",
            })

        # Check unit price.
        unit_price = None

        try:
            unit_price = float(
                str(row.get("unit_price") or "").strip()
            )

            if unit_price < 0:
                issues.append({
                    "Row ID": row_id,
                    "Transaction ID": transaction_id,
                    "Issue": "Negative unit price",
                })

        except (ValueError, TypeError):
            issues.append({
                "Row ID": row_id,
                "Transaction ID": transaction_id,
                "Issue": "Unit price is missing or invalid",
            })

        payment_status = str(
            row.get("payment_status") or ""
        ).strip().lower()

        # Current revenue eligibility rules.
        # A missing customer ID alone does not exclude revenue.
        if (
            transaction_id
            and not is_duplicate
            and payment_status == "paid"
            and quantity is not None
            and quantity > 0
            and unit_price is not None
            and unit_price >= 0
        ):
            accepted.append({
                "transaction_id": transaction_id,
                "order_date": str(
                    row.get("order_date") or ""
                ).strip(),
                "product": row.get("product") or "(unknown)",
                "quantity": quantity,
                "unit_price": unit_price,
                "revenue": quantity * unit_price,
            })

    return issues, accepted


# ==================================================
# 4. DAILY REVENUE MONITORING
# ==================================================

def calculate_daily_revenue(accepted):
    daily_totals = {}

    for transaction in accepted:
        date = transaction["order_date"] or "(missing date)"

        daily_totals[date] = (
            daily_totals.get(date, 0.0)
            + transaction["revenue"]
        )

    results = []
    previous_revenue = None

    for date, revenue in sorted(daily_totals.items()):
        percentage_change = None
        status = "Baseline"

        if previous_revenue is not None:

            if previous_revenue == 0:
                if revenue != 0:
                    status = "Potential anomaly"
            else:
                percentage_change = (
                    (revenue - previous_revenue)
                    / abs(previous_revenue)
                ) * 100

                if abs(percentage_change) > ANOMALY_THRESHOLD:
                    status = "Potential anomaly"
                else:
                    status = "Within threshold"

        results.append({
            "Date": date,
            "Revenue": round(revenue, 2),
            "Change vs previous date (%)": (
                round(percentage_change, 2)
                if percentage_change is not None
                else None
            ),
            "Status": status,
        })

        previous_revenue = revenue

    return results


# ==================================================
# 5. LOAD ANOMALY EVIDENCE
# ==================================================

def load_evidence():
    if not EVIDENCE_FILE.exists():
        return {}

    return json.loads(
        EVIDENCE_FILE.read_text(encoding="utf-8")
    )


# ==================================================
# 6. DASHBOARD HEADER AND DATA LOADING
# ==================================================

st.title("🔎 TruthTrail")
st.caption(
    "AI-Powered Data Detective | "
    "Data Quality • SQL • Analytics • Local AI"
)

with st.sidebar:
    st.header("Project Overview")
    st.write("**Data source:** SQLite")
    st.write(f"**Anomaly threshold:** {ANOMALY_THRESHOLD:.0f}%")
    st.write("**AI engine:** Ollama + Qwen3 4B")
    st.caption("AI reports run locally; no paid API is required.")

try:
    transactions = load_transactions()
    issues, accepted = analyze_transactions(transactions)
    daily_results = calculate_daily_revenue(accepted)
    evidence = load_evidence()
    incidents = evidence.get("incidents", [])

except (
    sqlite3.Error,
    OSError,
    ValueError,
    json.JSONDecodeError,
) as error:
    st.error(f"Could not load TruthTrail data: {error}")
    st.stop()

total_revenue = sum(
    transaction["revenue"] for transaction in accepted
)

# Top-level summary cards.
metric1, metric2, metric3, metric4 = st.columns(4)

metric1.metric("Transactions", len(transactions))
metric2.metric("Revenue-eligible", len(accepted))
metric3.metric("Eligible revenue", f"{total_revenue:,.2f}")
metric4.metric("Anomalies recorded", len(incidents))

st.divider()

overview_tab, quality_tab, anomaly_tab, report_tab, raw_tab = st.tabs([
    "📊 Overview",
    "🛡️ Data Quality",
    "🚨 Anomaly Investigation",
    "🤖 AI Report",
    "📋 Transactions",
])


# ==================================================
# 7. OVERVIEW TAB
# ==================================================

with overview_tab:
    st.subheader("Daily Revenue Trend")

    if daily_results:
        daily_df = pd.DataFrame(daily_results)

        chart_df = daily_df.set_index("Date")[["Revenue"]]
        st.line_chart(chart_df)

        st.subheader("Daily Revenue Summary")

        st.dataframe(
            daily_df,
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.info("No revenue-eligible transactions are available.")

    st.caption(
        "Anomaly alerts require investigation and are not proof "
        "of errors. Revenue amounts use the dataset's units; "
        "no currency is assumed."
    )


# ==================================================
# 8. DATA QUALITY TAB
# ==================================================

with quality_tab:
    st.subheader("Data Quality Findings")
    st.write(f"**Findings detected:** {len(issues)}")

    if issues:
        issues_df = pd.DataFrame(issues)

        st.dataframe(
            issues_df,
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.success("No data-quality issues detected.")

    st.caption(
        "A missing customer ID does not automatically exclude a "
        "transaction from revenue when the other eligibility "
        "rules are satisfied."
    )


# ==================================================
# 9. ANOMALY INVESTIGATION TAB
# ==================================================

with anomaly_tab:
    st.subheader("Detected Revenue Anomalies")

    if incidents:

        for index, incident in enumerate(incidents, start=1):
            previous_date = incident.get(
                "previous_date", "Unknown"
            )
            current_date = incident.get(
                "current_date", "Unknown"
            )

            st.markdown(
                f"### Incident {index}: "
                f"{previous_date} → {current_date}"
            )

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Previous Revenue",
                f"{incident.get('previous_revenue', 0):,.2f}",
            )

            col2.metric(
                "Current Revenue",
                f"{incident.get('current_revenue', 0):,.2f}",
            )

            percentage = incident.get("percentage_change")

            percentage_text = (
                f"{percentage:+,.2f}%"
                if percentage is not None
                else "N/A"
            )

            col3.metric(
                "Percentage Change",
                percentage_text,
            )

            st.write(
                "**Absolute change:** "
                f"{incident.get('absolute_change', 0):+,.2f}"
            )

            contributors = incident.get(
                "largest_product_contributors", []
            )

            if contributors:
                st.write("**Largest Product-Level Contributors**")

                st.dataframe(
                    pd.DataFrame(contributors),
                    use_container_width=True,
                    hide_index=True,
                )

            st.info(
                "Product-level changes are measured contributors, "
                "not proof of the underlying cause."
            )

            st.divider()

    else:
        st.info(
            "No incident evidence found. Run "
            "python incident_evidence.py to generate it."
        )


# ==================================================
# 10. AI REPORT TAB - BACKGROUND GENERATION
# ==================================================

with report_tab:
    st.subheader("Local AI Incident Report")

    st.write(
        "Generate an incident report using the evidence file and "
        "the local Qwen3 model running through Ollama."
    )

    # Keep track of the background process across reruns.
    if "ai_report_process" not in st.session_state:
        st.session_state["ai_report_process"] = None

    process = st.session_state["ai_report_process"]

    if st.button("Generate / refresh AI report", type="primary"):

        if process is not None and process.poll() is None:
            st.warning("A report is already being generated.")

        else:
            try:
                REPORT_FILE.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                with LOG_FILE.open("w", encoding="utf-8") as log:
                    process = subprocess.Popen(
                        [sys.executable, str(AI_SCRIPT)],
                        cwd=str(PROJECT_DIR),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        text=True,
                        creationflags=getattr(
                            subprocess,
                            "CREATE_NO_WINDOW",
                            0,
                        ),
                    )

                st.session_state["ai_report_process"] = process

                st.success(
                    "AI report generation started in the background."
                )

            except OSError as error:
                st.error(f"Could not start report generation: {error}")

    # Clicking this button reruns the dashboard and checks the status.
    st.button("Check report status")

    process = st.session_state["ai_report_process"]

    if process is not None:
        return_code = process.poll()

        if return_code is None:
            st.info(
                "Qwen3 is still generating the report. "
                "You can use the other tabs while it runs. "
                "Click 'Check report status' later."
            )

        elif return_code == 0:
            st.success("The report-generation script finished.")

        else:
            st.error(
                f"Report generation failed (exit code {return_code})."
            )

            if LOG_FILE.exists():
                log_text = LOG_FILE.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

                if log_text.strip():
                    st.code(log_text[-4000:])

    st.divider()
    st.subheader("Latest Saved Report")

    if REPORT_FILE.exists():
        report_text = REPORT_FILE.read_text(
            encoding="utf-8"
        ).strip()

        if report_text:
            st.caption(
                "This is the most recently saved report. "
                "It may be an earlier report if a new generation "
                "is still running."
            )

            st.markdown(report_text)

        else:
            st.info("The saved report is empty.")

    else:
        st.info(
            "No report has been saved yet. "
            "Use the button above to generate one."
        )


# ==================================================
# 11. TRANSACTIONS TAB
# ==================================================

with raw_tab:
    st.subheader("Transaction Records")

    if transactions:
        transaction_df = pd.DataFrame(transactions)

        st.dataframe(
            transaction_df,
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.info("The database contains no transaction records.")


# ==================================================
# 12. FOOTER
# ==================================================

st.divider()

st.caption(
    "TruthTrail prototype | "
    "Python + SQL + SQLite + Streamlit + Ollama"
)
