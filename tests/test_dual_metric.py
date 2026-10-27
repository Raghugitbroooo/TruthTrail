"""Tests for the transparent gross/net anomaly-scoring helpers."""

import pandas as pd

from detect_gross_net_anomalies import classify_day, evaluate_metric


def test_insufficient_history_is_not_scored_as_an_anomaly():
    result = evaluate_metric(120.0, pd.Series([100.0, 105.0, 110.0]))

    assert result["history_count"] == 3
    assert result["is_anomaly"] is None
    assert result["detection_method"] == "insufficient_history"


def test_robust_mad_detects_a_large_positive_deviation():
    result = evaluate_metric(200.0, pd.Series([99.0, 100.0, 101.0, 100.0]))

    assert result["detection_method"] == "robust_mad"
    assert result["robust_z"] > 3.5
    assert result["is_anomaly"] is True


def test_robust_mad_does_not_flag_a_small_deviation():
    result = evaluate_metric(101.0, pd.Series([99.0, 100.0, 101.0, 100.0]))

    assert result["detection_method"] == "robust_mad"
    assert result["is_anomaly"] is False


def test_zero_mad_uses_percentage_change_fallback():
    history = pd.Series([100.0, 100.0, 100.0, 100.0])

    flagged = evaluate_metric(160.0, history)
    not_flagged = evaluate_metric(120.0, history)

    assert flagged["detection_method"] == "zero_mad_fallback"
    assert flagged["is_anomaly"] is True
    assert not_flagged["is_anomaly"] is False


def test_gross_spike_with_large_offsets_gets_distinct_classification():
    row = {
        "gross_history_count": 8,
        "net_history_count": 8,
        "gross_is_anomaly": True,
        "net_is_anomaly": False,
        "negative_adjustment_ratio": 0.84,
    }

    assert classify_day(row) == "GROSS_SPIKE_MOSTLY_OFFSET"


def test_anomalies_on_both_metrics_are_identified():
    row = {
        "gross_history_count": 8,
        "net_history_count": 8,
        "gross_is_anomaly": True,
        "net_is_anomaly": True,
        "negative_adjustment_ratio": 0.02,
    }

    assert classify_day(row) == "GROSS_AND_NET_ANOMALY"
