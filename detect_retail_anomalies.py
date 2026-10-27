from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
REPORT_DIR = PROJECT_DIR / "reports"

INPUT_FILE = REPORT_DIR / "retail_daily_metrics.csv"
OUTPUT_FILE = REPORT_DIR / "retail_anomaly_findings.csv"

METRIC = "gross_sales_after_exact_duplicate_exclusion_gbp"

HISTORY_WEEKS = 8
MIN_HISTORY = 4
ROBUST_Z_THRESHOLD = 3.5
ZERO_MAD_PERCENT_THRESHOLD = 50.0


def detect_anomalies(daily_data):
    daily_data = daily_data.copy()

    daily_data["date"] = pd.to_datetime(
        daily_data["date"],
        errors="coerce",
    )

    daily_data[METRIC] = pd.to_numeric(
        daily_data[METRIC],
        errors="coerce",
    )

    daily_data = (
        daily_data
        .dropna(subset=["date", METRIC])
        .sort_values("date")
        .reset_index(drop=True)
    )

    results = []

    for index, row in daily_data.iterrows():
        current_date = row["date"]
        current_value = float(row[METRIC])

        previous_rows = daily_data.iloc[:index]

        # Compare with earlier observations on the same weekday.
        same_weekday = previous_rows[
            previous_rows["date"].dt.dayofweek
            == current_date.dayofweek
        ][METRIC].tail(HISTORY_WEEKS)

        result = {
            "date": current_date.strftime("%Y-%m-%d"),
            "gross_sales_gbp": round(current_value, 2),
            "weekday": current_date.day_name(),
            "historical_observations": len(same_weekday),
            "baseline_median_gbp": None,
            "baseline_mad": None,
            "change_from_baseline_pct": None,
            "robust_z_score": None,
            "status": "Insufficient history",
            "detection_method": None,
        }

        if len(same_weekday) < MIN_HISTORY:
            results.append(result)
            continue

        baseline_median = float(same_weekday.median())

        absolute_deviations = (
            same_weekday - baseline_median
        ).abs()

        mad = float(absolute_deviations.median())

        difference = current_value - baseline_median

        result["baseline_median_gbp"] = round(
            baseline_median, 2
        )
        result["baseline_mad"] = round(mad, 2)

        if baseline_median != 0:
            percentage_change = (
                difference / abs(baseline_median)
            ) * 100

            result["change_from_baseline_pct"] = round(
                percentage_change, 2
            )

        # Robust z-score based on the historical median and MAD.
        if mad > 0:
            robust_z = 0.6745 * difference / mad

            result["robust_z_score"] = round(robust_z, 3)

            is_anomaly = (
                abs(robust_z) > ROBUST_Z_THRESHOLD
            )

            result["detection_method"] = (
                "Same-weekday median and MAD"
            )

        else:
            # If historical values are identical, MAD is zero.
            # Use a documented relative-change fallback.
            threshold = max(
                abs(baseline_median)
                * ZERO_MAD_PERCENT_THRESHOLD / 100,
                1.0,
            )

            is_anomaly = abs(difference) > threshold

            result["detection_method"] = (
                "Same-weekday median; zero-MAD fallback"
            )

        result["status"] = (
            "Potential anomaly"
            if is_anomaly
            else "Within baseline"
        )

        results.append(result)

    return pd.DataFrame(results)


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Daily metrics not found: {INPUT_FILE}\n"
            "Run python build_retail_analytics.py first."
        )

    daily_data = pd.read_csv(INPUT_FILE)

    if "date" not in daily_data.columns:
        raise ValueError("Required column 'date' is missing.")

    if METRIC not in daily_data.columns:
        raise ValueError(
            f"Required metric column is missing: {METRIC}"
        )

    print("TruthTrail - Retail Anomaly Detection")
    print("=" * 45)

    print(
        "Metric: Gross sales after exact-duplicate candidate exclusion"
    )
    print(
        f"Historical window: Up to {HISTORY_WEEKS} previous "
        "observations for the same weekday"
    )
    print(
        f"Minimum history required: {MIN_HISTORY} observations"
    )

    findings = detect_anomalies(daily_data)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    findings.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    potential = findings[
        findings["status"] == "Potential anomaly"
    ]

    insufficient = findings[
        findings["status"] == "Insufficient history"
    ]

    print(f"\nDaily records examined: {len(findings):,}")
    print(f"Potential anomalies flagged: {len(potential):,}")
    print(f"Insufficient-history records: {len(insufficient):,}")

    print("\nLargest deviations from baseline:")

    ranked = (
        potential
        .assign(
            absolute_change=lambda df: (
                df["change_from_baseline_pct"].abs()
            )
        )
        .sort_values(
            "absolute_change",
            ascending=False,
            na_position="last",
        )
        .head(10)
    )

    if ranked.empty:
        print("No potential anomalies were flagged.")
    else:
        columns = [
            "date",
            "weekday",
            "gross_sales_gbp",
            "baseline_median_gbp",
            "change_from_baseline_pct",
            "robust_z_score",
            "detection_method",
        ]

        print(ranked[columns].to_string(index=False))

    print(f"\nFull results saved to: {OUTPUT_FILE}")
    print(
        "Alerts are investigation candidates, not proof of errors."
    )


if __name__ == "__main__":
    main()