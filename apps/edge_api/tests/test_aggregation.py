from datetime import datetime, timezone

from balut_api.aggregation import aggregate_inspection
from balut_api.domain import (
    Authority,
    ClassProbabilities,
    InspectionIngest,
    InspectionOutcome,
    MachineFlag,
    ViewAssessment,
)


def make_ingest(
    probabilities: ClassProbabilities,
    *,
    valid_views: int = 8,
    elapsed_hours: float | None = 384,
    device_flags: list[MachineFlag] | None = None,
) -> InspectionIngest:
    return InspectionIngest(
        inspection_id="TEST-INSPECTION-001",
        device_id="SIM-ESP32-S3-01",
        batch_id="SIM-BATCH-001",
        egg_id="SIM-EGG-001",
        recorded_elapsed_hours=elapsed_hours,
        model_release_id="TEST-MODEL",
        threshold_profile_id="TEST-THRESHOLDS",
        firmware_version="test",
        views=[
            ViewAssessment(
                view_index=index,
                angle_degrees=index * 45,
                quality_valid=index < valid_views,
                probabilities=probabilities,
                flags=[] if index < valid_views else [MachineFlag.IMAGE_BLURRED],
            )
            for index in range(8)
        ],
        device_flags=device_flags or [],
        captured_at=datetime.now(timezone.utc),
        is_simulated=True,
        authority=Authority.SHADOW_ONLY,
    )


def test_high_confidence_day_16_is_appearance_only():
    decision = aggregate_inspection(
        make_ingest(
            ClassProbabilities(
                day_16_like=0.90, day_18_like=0.06, reject_suspect=0.04
            )
        )
    )
    assert decision.outcome == InspectionOutcome.DAY_16_LIKE
    assert decision.authority == Authority.SHADOW_ONLY
    assert "source of truth" in decision.explanation


def test_incomplete_capture_fails_closed():
    decision = aggregate_inspection(
        make_ingest(
            ClassProbabilities(
                day_16_like=0.92, day_18_like=0.05, reject_suspect=0.03
            ),
            valid_views=5,
        )
    )
    assert decision.outcome == InspectionOutcome.REVIEW_RECAPTURE
    assert MachineFlag.INCOMPLETE_ROTATION in decision.flags


def test_low_confidence_fails_closed():
    decision = aggregate_inspection(
        make_ingest(
            ClassProbabilities(
                day_16_like=0.39, day_18_like=0.34, reject_suspect=0.27
            )
        )
    )
    assert decision.outcome == InspectionOutcome.REVIEW_RECAPTURE
    assert MachineFlag.LOW_CONFIDENCE in decision.flags


def test_known_age_conflict_fails_closed():
    decision = aggregate_inspection(
        make_ingest(
            ClassProbabilities(
                day_16_like=0.06, day_18_like=0.90, reject_suspect=0.04
            ),
            elapsed_hours=384,
        )
    )
    assert decision.outcome == InspectionOutcome.REVIEW_RECAPTURE
    assert MachineFlag.AGE_APPEARANCE_MISMATCH in decision.flags


def test_reject_is_only_a_model_suspect_flag():
    decision = aggregate_inspection(
        make_ingest(
            ClassProbabilities(
                day_16_like=0.05, day_18_like=0.05, reject_suspect=0.90
            )
        )
    )
    assert decision.outcome == InspectionOutcome.REJECT_SUSPECT
    assert decision.flags == [MachineFlag.MODEL_REJECT_SUSPECT]
    assert "not a food-safety" in decision.explanation


def test_device_fault_always_fails_closed():
    decision = aggregate_inspection(
        make_ingest(
            ClassProbabilities(
                day_16_like=0.92, day_18_like=0.05, reject_suspect=0.03
            ),
            device_flags=[MachineFlag.DEVICE_FAULT],
        )
    )
    assert decision.outcome == InspectionOutcome.REVIEW_RECAPTURE
    assert MachineFlag.DEVICE_FAULT in decision.flags

