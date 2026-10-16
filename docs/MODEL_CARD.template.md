# Model card — template, no released model

## Identity

- Release ID: `NOT ASSIGNED`
- Status: `BLOCKED — NO TRAINED MODEL`
- Backbone / input: MobileNetV2-0.35, 128×128 RGB initial candidate
- Class order: `DAY_16_LIKE`, `DAY_18_LIKE`, `REJECT_SUSPECT`
- Decision authority: appearance assessment only
- Intended hardware: reviewed ESP32-S3 target using ESP-DL int8

## Intended use

Eight-view, standardized candling research prototype for Balut vendors. The
model estimates appearance consistency and may abstain. It does not determine
microbiological safety, pathogens, edibility, legal grade, sale, or disposal.

## Dataset provenance

- Dataset manifest hash: `PENDING`
- Unique physical eggs: `PENDING`
- Batches / suppliers / devices / operators: `PENDING`
- Chronological capture windows and protocol version: `PENDING`
- Reviewer identities/qualifications and agreement: `PENDING`
- Excluded/unresolved counts and reasons: `PENDING`
- Prospective-test designation timestamp: `PENDING`

## Locked preprocessing and release contract

Record crop/localization, color order, normalization, exposure/calibration
version, quantization parameters, quality-gate version, aggregation thresholds,
firmware compatibility, model checksum, validation-report checksum, approval,
and rollback release. Any blank item blocks activation.

## Evaluation

Report egg-session confusion matrix; balanced accuracy; precision, recall,
specificity, and F1 per class; false rejection; automatic-reject precision;
review/recapture rate; accuracy versus coverage; calibration; batch/supplier/
operator/device slices; float/int8/ESP32 agreement; latency; peak memory;
temperature; energy; exclusions; failures; abstentions; and 95% intervals.

| Gate | Target | Result | 95% CI | Status |
|---|---:|---:|---:|---|
| Automatic-decision coverage | ≥70% | — | — | BLOCKED |
| Balanced accuracy among decided | ≥90% | — | — | BLOCKED |
| Recall per class among decided | ≥85% | — | — | BLOCKED |
| Int8 loss from float | ≤2 points | — | — | BLOCKED |

## Limitations and ethical boundary

Document batch shift, breed/supplier/device dependence, candling opacity,
reason-level reject limitations, unresolved cases, usability failure modes, and
all unsupported populations/conditions. A missed target preserves shadow mode;
it does not justify threshold tuning on the prospective test.
