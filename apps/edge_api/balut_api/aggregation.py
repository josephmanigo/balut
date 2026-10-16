from __future__ import annotations

from dataclasses import dataclass

from .domain import (
    AggregateDecision,
    Authority,
    ClassProbabilities,
    InspectionIngest,
    InspectionOutcome,
    InspectionState,
    MachineFlag,
)


@dataclass(frozen=True)
class ThresholdProfile:
    minimum_valid_views: int = 6
    minimum_confidence: float = 0.82
    minimum_margin: float = 0.15
    minimum_agreement: float = 0.625
    day_16_min_hours: float = 372.0
    day_16_max_hours: float = 396.0
    day_18_min_hours: float = 420.0
    day_18_max_hours: float = 444.0


QUALITY_FLAGS = {
    MachineFlag.IMAGE_TOO_DARK,
    MachineFlag.IMAGE_SATURATED,
    MachineFlag.IMAGE_BLURRED,
    MachineFlag.EGG_NOT_FOUND,
}


def _mean_probabilities(ingest: InspectionIngest):
    valid = [
        view
        for view in ingest.views
        if view.quality_valid and not QUALITY_FLAGS.intersection(view.flags)
    ]
    if not valid:
        return valid, ClassProbabilities(
            day_16_like=1 / 3,
            day_18_like=1 / 3,
            reject_suspect=1 / 3,
        )
    count = len(valid)
    return valid, ClassProbabilities(
        day_16_like=sum(v.probabilities.day_16_like for v in valid) / count,
        day_18_like=sum(v.probabilities.day_18_like for v in valid) / count,
        reject_suspect=sum(v.probabilities.reject_suspect for v in valid) / count,
    )


def _expected_age_outcome(
    elapsed_hours: float | None, profile: ThresholdProfile
) -> InspectionOutcome | None:
    if elapsed_hours is None:
        return None
    if profile.day_16_min_hours <= elapsed_hours <= profile.day_16_max_hours:
        return InspectionOutcome.DAY_16_LIKE
    if profile.day_18_min_hours <= elapsed_hours <= profile.day_18_max_hours:
        return InspectionOutcome.DAY_18_LIKE
    return None


def aggregate_inspection(
    ingest: InspectionIngest, profile: ThresholdProfile | None = None
) -> AggregateDecision:
    profile = profile or ThresholdProfile()
    valid, means = _mean_probabilities(ingest)
    flags = set(ingest.device_flags)
    for view in ingest.views:
        flags.update(view.flags)

    ranked = sorted(means.as_outcomes().items(), key=lambda pair: pair[1], reverse=True)
    top_outcome, confidence = ranked[0]
    margin = max(0.0, confidence - ranked[1][1])
    agreement = (
        sum(
            1
            for view in valid
            if max(
                view.probabilities.as_outcomes(),
                key=view.probabilities.as_outcomes().get,
            )
            == top_outcome
        )
        / len(valid)
        if valid
        else 0.0
    )

    review_reasons: list[str] = []
    if MachineFlag.DEVICE_FAULT in flags:
        review_reasons.append("device fault")
    if len(valid) < profile.minimum_valid_views:
        flags.add(MachineFlag.INCOMPLETE_ROTATION)
        review_reasons.append("fewer than six valid views")
    if confidence < profile.minimum_confidence or margin < profile.minimum_margin:
        flags.add(MachineFlag.LOW_CONFIDENCE)
        review_reasons.append("confidence or class margin below the simulator profile")
    if agreement < profile.minimum_agreement:
        flags.add(MachineFlag.VIEW_DISAGREEMENT)
        review_reasons.append("view-level predictions disagree")

    expected = _expected_age_outcome(ingest.recorded_elapsed_hours, profile)
    if (
        expected is not None
        and top_outcome
        in {InspectionOutcome.DAY_16_LIKE, InspectionOutcome.DAY_18_LIKE}
        and expected != top_outcome
    ):
        flags.add(MachineFlag.AGE_APPEARANCE_MISMATCH)
        review_reasons.append("recorded incubation age conflicts with appearance")

    if review_reasons:
        return AggregateDecision(
            outcome=InspectionOutcome.REVIEW_RECAPTURE,
            state=InspectionState.REVIEW_REQUIRED,
            confidence=confidence,
            margin=margin,
            agreement=agreement,
            valid_views=len(valid),
            mean_probabilities=means,
            flags=sorted(flags, key=str),
            authority=ingest.authority,
            explanation="Review required: " + "; ".join(dict.fromkeys(review_reasons)) + ".",
        )

    if top_outcome == InspectionOutcome.REJECT_SUSPECT:
        flags.add(MachineFlag.MODEL_REJECT_SUSPECT)
        explanation = (
            "Appearance-only reject suspect. Segregate and obtain human review; "
            "this is not a food-safety or spoilage confirmation."
        )
    else:
        explanation = (
            f"Appearance is consistent with {top_outcome.value.replace('_', ' ').title()}. "
            "Recorded incubation age remains the chronological source of truth."
        )

    return AggregateDecision(
        outcome=top_outcome,
        state=InspectionState.COMPLETED,
        confidence=confidence,
        margin=margin,
        agreement=agreement,
        valid_views=len(valid),
        mean_probabilities=means,
        flags=sorted(flags, key=str),
        authority=ingest.authority,
        explanation=explanation,
    )

