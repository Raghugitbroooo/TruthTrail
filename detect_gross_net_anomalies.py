from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent

INPUT_PATH = (
    PROJECT_DIR
    / "reports"
    / "retail_daily_gross_net_metrics.csv"
)

OUTPUT_PATH = (
    PROJECT_DIR
    / "reports"
    / "retail_dual_metric_anomalies.csv"
)

HISTORY_WINDOW = 8
MIN_HISTORY = 4
ROBUST_Z_THRESHOLD = 3.5
PERCENT_CHANGE_FALLBACK = 0.50
LARGE_OFFSET_RATIO = 0.50

METRICS = {
    "gross": "gross_positive_sales",
    "net": "net_transaction_line_value",
}


def evaluate_metric(current_value, historic_values):
    """
    Evaluate one value against previous dates with the same weekday.

    Uses the median absolute deviation (MAD) when available.
    When MAD is zero, falls back to a 50% change rule.
    """

    history = pd.to_numeric(
        historic_values, errors="coerce"
    ).dropna().tail(HISTORY_WINDOW)

    result = {
        "history_count": int(len(history)),
        "baseline_median": np.nan,
        "baseline_mad": np.nan,
        "robust_z": np.nan,
        "change_percent": np.nan,
        "is_anomaly": None,
        "detection_method": "insufficient_history",
    }

    if len(history) < MIN_HISTORY:
        return result

    current_value = float(current_value)
    baseline_median = float(history.median())

    deviations = (history - baseline_median).abs()
    mad = float(deviations.median())

    if abs(baseline_median) > 1e-12:
        change_percent = (
            (current_value - baseline_median)
            / abs(baseline_median)
            * 100
        )
    else:
        change_percent = np.nan

    result["baseline_median"] = baseline_median
    result["baseline_mad"] = mad
    result["change_percent"] = change_percent

    if mad > 1e-12:
        robust_z = (
            0.6745
            * (current_value - baseline_median)
            / mad
        )

        result["robust_z"] = float(robust_z)
        result["is_anomaly"] = (
            abs(robust_z) >= ROBUST_Z_THRESHOLD
        )
        result["detection_method"] = "robust_mad"

    else:
        # MAD can be zero when historical values are very similar.
        # In that case, use a percentage fallback instead.
        difference = abs(current_value - baseline_median)

        if abs(baseline_median) > 1e-12:
            threshold = (
                PERCENT_CHANGE_FALLBACK
                * abs(baseline_median)
            )
        else:
            threshold = 0.01

        result["is_anomaly"] = difference > threshold
        result["detection_method"] = "zero_mad_fallback"

    return result


def format_money(value):
    if pd.isna(value):
        return "n/a"
    return f"£{value:,.2f}"


def format_percent(value):
    if pd.isna(value):
        return "n/a"
    return f"{value:+.2f}%"


def format_score(value):
    if pd.isna(value):
        return "n/a"
    return f"{value:+.2f}"


def classify_day(row):
    """Combine gross, net, and adjustment evidence."""

    if (
        row["gross_history_count"] < MIN_HISTORY
        or row["net_history_count"] < MIN_HISTORY
    ):
        return "INSUFFICIENT_HISTORY"

    gross_flag = bool(row["gross_is_anomaly"])
    net_flag = bool(row["net_is_anomaly"])
    offset_ratio = row["negative_adjustment_ratio"]

    large_offset = (
        pd.notna(offset_ratio)
        and offset_ratio >= LARGE_OFFSET_RATIO
    )

    if gross_flag and net_flag:
        if large_offset:
            return "GROSS_AND_NET_ANOMALY_WITH_LARGE_OFFSETS"
        return "GROSS_AND_NET_ANOMALY"

    if gross_flag and not net_flag:
        if large_offset:
            return "GROSS_SPIKE_MOSTLY_OFFSET"
        return "GROSS_ONLY_ANOMALY"

    if net_flag and not gross_flag:
        return "NET_ONLY_ANOMALY"

    return "NO_ANOMALY"


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Input report not found:\n{INPUT_PATH}\n\n"
            "Run compare_gross_net_revenue.py first."
        )

    data = pd.read_csv(INPUT_PATH)

    required_columns = {
        "transaction_date",
        "gross_positive_sales",
        "net_transaction_line_value",
        "returns_cancellations_value",
        "unique_source_lines",
    }

    missing = required_columns - set(data.columns)

    if missing:
        raise ValueError(
            "The input report is missing columns: "
            + ", ".join(sorted(missing))
        )

    data["date_value"] = pd.to_datetime(
        data["transaction_date"], errors="coerce"
    )

    for column in METRICS.values():
        data[column] = pd.to_numeric(
            data[column], errors="coerce"
        )

    data = (
        data.dropna(subset=["date_value"])
        .sort_values("date_value")
        .drop_duplicates(subset=["transaction_date"])
        .reset_index(drop=True)
    )

    print("TruthTrail - Gross and Net Anomaly Detection")
    print("=" * 58)
    print(f"Daily records loaded: {len(data):,}")
    print(f"Historical window: {HISTORY_WINDOW} same-weekday dates")
    print(f"Minimum historical observations: {MIN_HISTORY}")
    print(f"Robust z-score threshold: {ROBUST_Z_THRESHOLD}")
    print()

    results = []

    for index, row in data.iterrows():
        current_date = row["date_value"]
        previous = data.iloc[:index]

        same_weekday = previous[
            previous["date_value"].dt.day_of_week
            == current_date.day_of_week
        ]

        record = row.drop(labels=["date_value"]).to_dict()

        for metric_name, column_name in METRICS.items():
            evaluated = evaluate_metric(
                row[column_name],
                same_weekday[column_name],
            )

            for field, value in evaluated.items():
                record[f"{metric_name}_{field}"] = value

        gross = row["gross_positive_sales"]
        net = row["net_transaction_line_value"]

        if pd.notna(gross) and gross > 0 and pd.notna(net):
            record["negative_adjustment_ratio"] = max(
                0.0, (gross - net) / gross
            )
        else:
            record["negative_adjustment_ratio"] = np.nan

        record["classification"] = classify_day(record)
        results.append(record)

    report = pd.DataFrame(results)

    OUTPUT_PATH.parent.mkdir(
        parents=True, exist_ok=True
    )
    report.to_csv(OUTPUT_PATH, index=False)

    gross_flags = report["gross_is_anomaly"].eq(True)
    net_flags = report["net_is_anomaly"].eq(True)

    evaluated = report[
        (report["gross_history_count"] >= MIN_HISTORY)
        & (report["net_history_count"] >= MIN_HISTORY)
    ]

    print("DETECTION SUMMARY")
    print("-" * 58)
    print(f"Dates analyzed: {len(report):,}")
    print(
        "Dates with enough baseline history: "
        f"{len(evaluated):,}"
    )
    print(f"Potential gross anomalies: {gross_flags.sum():,}")
    print(f"Potential net anomalies: {net_flags.sum():,}")
    print()

    print("CLASSIFICATION COUNTS")
    print("-" * 58)
    counts = report["classification"].value_counts()

    for classification, count in counts.items():
        print(f"{classification}: {count}")

    target_dates = [
        "2011-09-20",
        "2011-07-28",
        "2011-12-09",
        "2011-06-10",
        "2011-11-14",
    ]

    selected = report[
        report["transaction_date"].astype(str).isin(
            target_dates
        )
    ].copy()

    print()
    print("FIVE INVESTIGATED DATES")
    print("-" * 100)
    print(
        f"{'Date':<13}"
        f"{'Gross sales':>16}"
        f"{'Net value':>16}"
        f"{'Gross change':>15}"
        f"{'Net change':>14}"
        f"{'Gross Z':>10}"
        f"{'Net Z':>10}"
    )
    print("-" * 100)

    for _, row in selected.iterrows():
        print(
            f"{str(row['transaction_date']):<13}"
            f"{format_money(row['gross_positive_sales']):>16}"
            f"{format_money(row['net_transaction_line_value']):>16}"
            f"{format_percent(row['gross_change_percent']):>15}"
            f"{format_percent(row['net_change_percent']):>14}"
            f"{format_score(row['gross_robust_z']):>10}"
            f"{format_score(row['net_robust_z']):>10}"
        )
        print(f"  Classification: {row['classification']}")
        print(
            "  Negative adjustment share: "
            f"{format_percent(row['negative_adjustment_ratio'] * 100)}"
        )

    print()
    print(f"Full results saved to:\n{OUTPUT_PATH}")
    print()
    print(
        "These are candidate anomalies based on historical patterns. "
        "They do not prove that any transaction is wrong."
    )


if __name__ == "__main__":
    main()