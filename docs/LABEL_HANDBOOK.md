# Label and disposition handbook

## Machine appearance classes

- `DAY_16_LIKE`: captured morphology resembles the frozen Day 16 appearance
  profile. It is not chronological ground truth and not a food-safety grade.
- `DAY_18_LIKE`: captured morphology resembles the frozen Day 18 appearance
  profile. It is not chronological ground truth and not a food-safety grade.
- `REJECT_SUSPECT`: the validated model crosses the frozen anomaly threshold.
  It requires segregation and human confirmation; it is not “rotten confirmed.”
- `REVIEW_RECAPTURE`: insufficient or conflicting evidence, an age mismatch, or
  a device/quality fault prevents automatic use.

## Human reason codes

Preserve these as distinct observations. Never infer them from the three-class
machine output unless a reason-level model is separately collected and
validated:

- `SHELL_DAMAGE_OBSERVED`
- `INFERTILITY_SUSPECTED`
- `EMBRYONIC_DEATH_SUSPECTED`
- `BLOOD_RING_OBSERVED`
- `VISIBLE_DECOMPOSITION_SUSPECTED`
- `AGE_DOCUMENTATION_CONFLICT`
- `IMAGE_OR_ROTATION_INADEQUATE`
- `UNKNOWN_ANOMALY`

Two reviewers independently record their dispositions before discussion. Store
each original rating, blindness state, reason codes, timestamp, and identity.
Adjudication appends a later record; it does not overwrite either rating.
Unresolved cases stay `UNRESOLVED` and do not enter supervised training or
primary test metrics.

## Banned transformations and wording

- Do not map PNS shell-egg `AA`, `A`, or `B` terminology to Balut grades.
- Do not silently map public `Reject`, `Bulok`, `Fertilized`, or generic `Balut`
  labels to exact age, rottenness, embryonic death, or safety.
- Do not display `SAFE TO EAT`, `ROTTEN CONFIRMED`, `PATHOGEN-FREE`,
  `SALMONELLA-FREE`, “certified,” “sell,” or “dispose” as a machine conclusion.
- Do not let a reviewer overwrite an immutable machine result.
