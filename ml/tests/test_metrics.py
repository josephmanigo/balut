import pytest

from balut_ml.metrics import SessionPrediction, compare_float_int8, evaluate_selective_classification, wilson_interval


def test_selective_metrics_keep_abstentions_in_coverage() -> None:
    rows = [
        SessionPrediction("S1", "DAY_16_LIKE", "DAY_16_LIKE", 0.9, True),
        SessionPrediction("S2", "DAY_18_LIKE", "DAY_18_LIKE", 0.9, True),
        SessionPrediction("S3", "REJECT_SUSPECT", "REJECT_SUSPECT", 0.9, True),
        SessionPrediction("S4", "DAY_16_LIKE", "REVIEW_RECAPTURE", 0.4, False),
    ]
    metrics = evaluate_selective_classification(rows)
    assert metrics["coverage"] == 0.75
    assert metrics["selective_accuracy"] == 1.0
    assert metrics["balanced_accuracy"] == 1.0


def test_float_int8_agreement_uses_only_shared_ids() -> None:
    result = compare_float_int8(
        [("S1", "DAY_16_LIKE"), ("S2", "DAY_18_LIKE")],
        [("S1", "DAY_16_LIKE"), ("S3", "REJECT_SUSPECT")],
    )
    assert result["shared_session_count"] == 1
    assert result["prediction_agreement"] == 1.0
    assert result["missing_from_float"] == 1
    assert result["missing_from_int8"] == 1


def test_wilson_interval_is_bounded() -> None:
    low, high = wilson_interval(90, 100)
    assert 0 < low < 0.9 < high < 1


def test_perfect_selective_accuracy_cannot_hide_a_class_that_always_recaptures():
    metrics = evaluate_selective_classification([
        SessionPrediction("S1", "DAY_16_LIKE", "DAY_16_LIKE", 0.9, True),
        SessionPrediction("S2", "DAY_18_LIKE", "DAY_18_LIKE", 0.9, True),
        SessionPrediction("S3", "REJECT_SUSPECT", "REVIEW_RECAPTURE", 0.4, False),
    ])
    assert metrics["selective_accuracy"] == 1
    assert metrics["automatic_support_complete"] is False
    assert metrics["end_to_end_balanced_accuracy"] == pytest.approx(2 / 3)
    assert metrics["per_class"]["REJECT_SUSPECT"]["abstained"] == 1
    assert metrics["per_class"]["REJECT_SUSPECT"]["end_to_end_recall"] == 0
    assert metrics["selective_accuracy_95ci"][0] < 0.5


@pytest.mark.parametrize("rows", [
    [SessionPrediction("S1", "DAY_16_LIKE", "DAY_16_LIKE", 0.9, True)] * 2,
    [SessionPrediction("S1", "UNKNOWN", "REVIEW_RECAPTURE", 0.4, False)],
    [SessionPrediction("S1", "DAY_16_LIKE", "DAY_16_LIKE", float("nan"), True)],
])
def test_invalid_or_duplicate_sessions_cannot_inflate_accuracy(rows):
    with pytest.raises(ValueError):
        evaluate_selective_classification(rows)


def test_impossible_counts_and_duplicate_parity_rows_are_rejected():
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(11, 10)
    with pytest.raises(ValueError):
        compare_float_int8([("S1", "DAY_16_LIKE")] * 2, [("S1", "DAY_16_LIKE")])
