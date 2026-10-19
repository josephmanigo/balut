# EggGrade IoT software hardening and accuracy comparison — 2026-10-04

Status: **verified Windows software for local shadow use**. Production physical grading remains blocked. The shipped model remains `automatic-recapture-20260912`; the new candidate is retained for research and is not activated.

## The three supplied archives

The three ZIP files in Downloads match the previously imported archives by SHA-256. Their CRC checks passed. The existing audited manifests and all 6,332 included images/crops were rechecked for image hashes and partition isolation: 173 age-source crops, 5,174 Pat crops, and 985 duck-source images. These counts include generated variants and multiple crops; they are not counts of independent eggs.

The age source supplies `Fertile-Day-16` and `Fertile-Day-18`. Only literal Pat `Reject` labels enter the three-class comparison. Duck `abnormal`, `fertile`, and `infertile` retain their original meanings and remain auxiliary research data. They are not remapped into age or reject ground truth. There are no new verified physical egg IDs, incubation timestamps, or independent candler test captures in these archives.

Evidence: [archive and image audit](../artifacts/training-input-audit-20261004.json).

## The bounded training comparison

The extended experiment fits 80 classifier candidates using the existing frozen image features: four DINOv2/ConvNeXt/EfficientNet fusion combinations and 20 regularization/head choices. Training fits use only the original training split. Validation macro F1, then balanced accuracy, then accuracy select the candidate. The experiment plan, development caches, selected head, development arrays, and gate policy are hashed before historical evaluation. The historical test does not select model parameters or thresholds.

The winner uses DINOv2 ViT-S/14 plus EfficientNet-B0 with a balanced logistic head at C=30. Its development result improves slightly, but its historical accepted result does not improve. No thresholds are changed after seeing historical errors. The previous model remains installed; the new candidate is not promoted.

| Metric | Current model | New candidate |
|---|---:|---:|
| Validation raw balanced accuracy | 87.50% | 89.17% |
| Validation raw macro F1 | 87.03% | 88.85% |
| Validation accepted correct / classified | 211 / 211 | 211 / 211 |
| Historical raw correct / images | 166 / 172 | 166 / 172 |
| Historical accepted correct / classified | 95 / 97 | 94 / 96 |
| Historical accepted accuracy | 97.94% | 97.92% |
| Historical classification coverage | 56.40% | 55.81% |
| Historical wrong accepted predictions | 2 | 2 |

This historical holdout has been inspected in earlier experiments. These results are exploratory public-source comparisons, not a new independent accuracy estimate. The overall score is dominated by Reject images from a different source; lighting/background confounding and missing egg identities remain unresolved.

CPU PyTorch and ONNX agree on all 172 candidate raw predictions and every class/recapture decision. Maximum CPU score difference is 0.0000151; maximum embedding difference is 0.000000798. Larger GPU/CPU differences are preserved separately rather than concealed or used to change the model.

Evidence: [frozen experiment plan](../ml/runs/selective-v3-20261004/experiment-plan.json), [selection lock](../ml/runs/selective-v3-20261004/selection-lock.json), [candidate metrics](../ml/runs/selective-v3-20261004/metrics.json), [CPU ONNX parity](../ml/runs/selective-v3-20261004/onnx-parity.json).

## Implemented hardening

- Physical manifests now verify the actual image SHA-256, decoding, size limits, and relative-path containment. Identical decoded pixels with conflicting egg/partition/label identities are blocked even when file hashes differ.
- Duplicate original views, conflicting inspection identities, nonexistent augmentation parents, and augmentation identity changes are rejected. Non-finite ages are rejected. Repeated reviewer references do not count as two distinct references. Eight-view completeness and missing reviewer evidence remain visible audit warnings; a training audit is not physical release approval.
- Evaluation rejects duplicate session IDs, invalid abstention labels, impossible binomial counts, non-finite confidence, and duplicate float/int8 parity IDs. Reports include abstentions per class, coverage, correct classifications over all sessions, end-to-end recall, and 95% Wilson intervals. No samples yield a full uncertainty interval. These intervals assume independent trials; repeated sessions of one egg need clustered analysis.
- Startup checks every shipped class and recapture example, including its hash, raw scores, prediction, and exact recapture reasons. Tied scores request recapture even with a zero margin threshold. Boolean threshold values are rejected.
- Fresh package verification binds the API source and built dashboard hashes to the live test. A changed served file blocks packaging. Old archives are preserved. Private profiles, credentials, databases, operating evidence, and logs are excluded from the ZIP.

The stricter manifest audit reduces the risk of inflated training results. The startup checks reduce the risk of serving a broken release. Neither changes the deployed model weights or proves increased real-egg classification accuracy.

## Current verification

- Serving/core suite: 90 passed, five optional training checks skipped; three upstream warnings. Training environment: 25 focused checks passed. These suites overlap and must not be added together.
- Web: eight tests passed; TypeScript and production build passed.
- Real ONNX API: Day 16, Day 18, suspected Reject, dark-image recapture, and ambiguous-image recapture passed. Authentication, invalid JPEG rejection, retry idempotency, abrupt process restart, and backup/restore passed. Fifteen test prediction records and five evidence images survive restoration.
- Edge browser: all five outcomes and replacement-image behavior passed at 1440×1000 and 390×844, with no horizontal overflow or browser errors. No mandatory review step is added.
- Fresh npm and pinned Python dependency audits report zero known vulnerabilities at scan time. This is a dated scan, not a guarantee against future findings.

Evidence: [API tests](../artifacts/hardening-20261004-api-tests.xml), [training checks](../artifacts/hardening-20261004-ml-tests.xml), [live verification](../artifacts/hardening-20261004-live-verification.json), [browser verification](../artifacts/hardening-20261004-ui-verification.json), [npm audit](../artifacts/hardening-20261004-npm-audit.json), [Python audit](../artifacts/hardening-20261004-python-audit.json). Fresh offline installation is recorded separately in `artifacts/hardening-20261004-offline-verification.json` after package construction.

## Use and next release gate

Start the existing installation with `scripts/Start-Balut.ps1 -Supervise`, then open `http://127.0.0.1:8765` in Chrome or Edge. Use the existing operator password through `scripts/Copy-Balut-Login.ps1`. Unclear images remain unclassified and require a replacement image; repeated uncertainty never forces a guess.

The new handoff is `artifacts/balut-hardened-20261004.zip`. It packages the hardened serving code, the retained model, the built dashboard, offline Windows x64/Python 3.12 dependencies, and verification records. On another Windows laptop, extract it and run `scripts/Install-Balut.ps1`, then `scripts/Copy-Balut-Login.ps1`, then `scripts/Start-Balut.ps1 -Supervise`.

The next accuracy gate is [identified, timestamped real-candler data](REAL_CANDLING_DATA_COLLECTION.md), captured with the same optics across all classes and split by complete eggs/batches. Freeze model and thresholds before opening a fresh prospective batch. The [physical and research acceptance ledger](VALIDATION_LEDGER.md) remains required. Production approval cannot be granted by a model score, a successful build, or a ready HTTP service. Physical interlock/transport tests and ESP32 int8/device acceptance remain open if the box performs grading.

Methods: [scikit-learn test-leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage) and [NIST proportion confidence intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).
