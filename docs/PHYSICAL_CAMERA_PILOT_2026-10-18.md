# Physical camera pilot — 18 October 2026

The user reports 15 uncooked Day 16 eggs and 15 uncooked Day 18 eggs from a balut farm, with ages confirmed by incubation dates. Exact incubation records, species, and batch IDs have not been supplied. This is an exploratory single-camera pilot, not population accuracy or grading authorization.

**Current status: all 30 verified live samples recorded; one candidate trained, locked, and tested once. Candidate not activated.** Ten initial records were quarantined under `excluded/unverified-frame-freshness` because intermittent USB acquisition did not drain the camera's queued frame. Their image-to-egg pairing is not established. They do not contribute to training or accuracy metrics. The fresh collection started with actual automatic scans of 16-4 and 18-4. Count only root-level egg records; excluded diagnostics never count.

Each egg contributes one retained image. The previously examined eggs are number 1 of each age. The initial five-per-age plan was expanded before recording the pilot; egg 5 remains reserved for the final test.

| Partition | IDs within each age | Total eggs |
| --- | --- | --- |
| Training | 1, 2, 3, 6, 7 | 10 |
| Validation | 4, 8, 9, 10, 11 | 10 |
| Final test | 5, 12, 13, 14, 15 | 10 |

Alternate ages during collection. Keep the same holder, camera framing, and lighting setup; hands and shell writing must stay out of view. Record each physical egg under exactly one ID. An excluded image remains outside the dataset with its reason recorded; replacement images retain the same egg ID. The first 18-2 image was excluded because shell writing was visible.

`scripts/capture_camera_pilot.py` discards the queued frame, then records one CRC-checked fresh JPEG from the identified USB camera, rotates it using the serving transform, and closes the port. It sends no motor commands. It rejects duplicate bytes, changed plans, framing changes, and overwriting an existing egg. Files and SHA-256 metadata live under `output/physical-pilot-20261018`; they are not automatically added to an active dataset or cloud prediction history. The evaluator requires the corrected freshness marker and refuses unverified source imports.

For the live workflow, use `--prediction UUID` to copy the evidence of an actual automatic camera result into the pilot. The importer verifies the result identity, real IoT-box origin, single-frame format, JPEG dimensions, and evidence hash. The user-confirmed egg ID supplies the age label, never the model's prediction. Confirm a new result after an observed empty-to-occupied transition before associating it with an egg. Test freshness uses the prediction's capture time, not the later import time.

For calibration without repeated empty-holder cycles, use `--live` after the user confirms the numbered egg is in place. This waits for two advancing camera updates, clearing any upload already in flight, then retains one frame from the running signed USB stream. It checks source dimensions, framing version, and absence of pending inference before accepting the current preview. The full-size preview is the same prepared camera frame used by inference. No previous prediction is relabeled, and no production prediction is fabricated. Capture time and the stream's frame key are recorded.

`ml/balut_ml/camera_pilot.py` fits one predefined binary logistic head (`C=10`, balanced classes) on the retained frozen fused features. Only training eggs fit the head. Validation reports compare raw candidate age correctness against the existing model, including that model's accepted accuracy, coverage, and correct predictions over all inputs. The candidate is diagnostic and issues no authorized classifications.

From the repository root in PowerShell, set `$env:PYTHONPATH = 'ml;apps/edge_api'`, then run `.venv-ml/Scripts/python.exe -m balut_ml.camera_pilot fit` after all development eggs are recorded. The script verifies the active registry and known-answer fixtures through `ModelService`, saves a portable head, checks numerical parity, and locks the artifacts, development-image hashes, plan, and evaluation script. Capture final-test eggs only after this lock. Run the same module with `test` once; changes to locked files or reuse of development images fail closed.

## Measured results

The candidate was locked at `2026-10-18T14:41:04.064832+00:00`, before any final-test capture. It was fitted on the ten training eggs only. The final test ran once after all ten reserved eggs were recorded; no model or threshold was adjusted from its results.

| Evaluation | Candidate raw age correct | Day 16 correct | Day 18 correct | Existing model raw correct |
| --- | --- | --- | --- | --- |
| Validation: 10 eggs | 9/10 | 5/5 | 4/5 | 6/10 |
| Final test: 10 untouched eggs | 10/10 | 5/5 | 5/5 | 4/10 |

The validation mistake was egg `18-4`, predicted as Day 16. The existing model issued no accepted classification on either evaluation: coverage was 0/10, correct classifications over all inputs was 0/10, and accepted accuracy was undefined because it abstained on every egg. The candidate's figures are raw binary age guesses, not accepted production classifications or calibrated confidence.

Evidence is saved in `output/physical-pilot-20261018/candidate/validation-report.json`, `test-report.json`, and `selection-lock.json`. The portable learned head is `age-head.npz`; the active feature encoder remains the verified retained release. The lock records the head, evaluation code, registry, plan, and all development-image hashes. The recorder rejects final-test capture before this lock exists.

**Deployment decision: retain the candidate for further physical validation.** No active classifier or uncertainty threshold is changed by this pilot. The default serving model requires Day 16, Day 18, and Reject support; this candidate was tested only on Day 16 and Day 18. No reject-class eggs or acceptance calibration for the new camera domain are available. Integration also needs a verified serving/export contract rather than substituting an unregistered binary head.

Ten held-out eggs from this collection cannot establish accuracy across farms, batches, lighting conditions, or future camera sessions. The measured improvement is promising for this setup, but the live app still uses the original classifier and can still report unfamiliar appearance. The next evidence should come from a separately documented batch/session and include reject/review examples; these 30 eggs are now development/evaluation evidence, not a fresh test set for another tuned candidate.

The deployed automatic flow separately changed to one analyzed JPEG per egg in commit `8025ba2`. Physical accuracy remains under investigation.

The user confirmed that the autonomous holder still rotates and has no separate motor switch. A temporary serial RTS reset hold on the identified CP210x motor adapter did not stop it, according to the user. The hold was released, the port closed, and no motor firmware was written. Earlier scan evidence and the quarantined pilot images were acquired with rotation. A stationary-holder claim is unsupported.
