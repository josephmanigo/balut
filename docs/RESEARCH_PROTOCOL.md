# Research protocol skeleton

This file is an implementation aid, not ethics approval or a completed protocol.

## Identity and chronology

- Assign a durable physical egg ID before the first capture.
- Store the incubator-entry timestamp with timezone and derive elapsed hours without rounding away the raw value.
- Keep every view, recapture, and Day 16/Day 18 session from one physical egg in one partition.
- Record supplier, breed/line when available, incubator, batch, device, operator, and interruptions.

## Label authority

- Two reviewers record independent dispositions before model output is revealed.
- Disagreement is preserved; an unresolved sample is excluded from supervised training and primary metrics.
- Reject reasons remain distinct and source-attributed.
- Public generic Balut, Fertilized, Reject, Bulok, or Rotten labels do not become exact-age or food-safety truth.

## Planned minimum cohort

- Development/validation: 140 viable physical eggs imaged at both target ages plus 70 confirmed reject-suspect eggs.
- Prospective external test: 60 new viable physical eggs imaged at both target ages plus 30 new reject-suspect eggs.
- Augmented images and multiple views are never counted as new eggs.

## Frozen evaluation

Freeze preprocessing, model weights, quantization, thresholds, aggregation, and schema before the prospective test. Report all abstentions and exclusions with 95% confidence intervals.

