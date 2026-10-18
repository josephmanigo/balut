# Physical camera pilot — 18 October 2026

The user reports 15 uncooked Day 16 eggs and 15 uncooked Day 18 eggs from a balut farm, with ages confirmed by incubation dates. Exact incubation records, species, and batch IDs have not been supplied. This is an exploratory single-camera pilot, not population accuracy or grading authorization.

**Current status: collecting verified live scans. No candidate trained.** Ten initial records were quarantined under `excluded/unverified-frame-freshness` because intermittent USB acquisition did not drain the camera's queued frame. Their image-to-egg pairing is not established. They must not contribute to training or accuracy metrics. The fresh collection starts with actual automatic scans of 16-4 and 18-4. Count only root-level egg records; excluded diagnostics never count.

Each egg contributes one retained image. The previously examined eggs are number 1 of each age. The initial five-per-age plan was expanded before recording the pilot; egg 5 remains reserved for the final test.

| Partition | IDs within each age | Total eggs |
| --- | --- | --- |
| Training | 1, 2, 3, 6, 7 | 10 |
| Validation | 4, 8, 9, 10, 11 | 10 |
| Final test | 5, 12, 13, 14, 15 | 10 |

Alternate ages during collection. Keep the same holder, camera framing, and lighting setup; hands and shell writing must stay out of view. Record each physical egg under exactly one ID. An excluded image remains outside the dataset with its reason recorded; replacement images retain the same egg ID. The first 18-2 image was excluded because shell writing was visible.

`scripts/capture_camera_pilot.py` discards the queued frame, then records one CRC-checked fresh JPEG from the identified USB camera, rotates it using the serving transform, and closes the port. It sends no motor commands. It rejects duplicate bytes, changed plans, framing changes, and overwriting an existing egg. Files and SHA-256 metadata live under `output/physical-pilot-20261018`; they are not automatically added to an active dataset or cloud prediction history. The evaluator requires the corrected freshness marker and refuses unverified source imports.

For the live workflow, use `--prediction UUID` to copy the evidence of an actual automatic camera result into the pilot. The importer verifies the result identity, real IoT-box origin, single-frame format, JPEG dimensions, and evidence hash. The user-confirmed egg ID supplies the age label, never the model's prediction. Confirm a new result after an observed empty-to-occupied transition before associating it with an egg. Test freshness uses the prediction's capture time, not the later import time.

`ml/balut_ml/camera_pilot.py` fits one predefined binary logistic head (`C=10`, balanced classes) on the retained frozen fused features. Only training eggs fit the head. Validation reports compare raw candidate age correctness against the existing model, including that model's accepted accuracy, coverage, and correct predictions over all inputs. The candidate is diagnostic and issues no authorized classifications.

From the repository root in PowerShell, set `$env:PYTHONPATH = 'ml;apps/edge_api'`, then run `.venv-ml/Scripts/python.exe -m balut_ml.camera_pilot fit` after all development eggs are recorded. The script verifies the active registry and known-answer fixtures through `ModelService`, saves a portable head, checks numerical parity, and locks the artifacts, development-image hashes, plan, and evaluation script. Capture final-test eggs only after this lock. Run the same module with `test` once; changes to locked files or reuse of development images fail closed.

No active classifier or uncertainty threshold is changed by this pilot. No reject-class eggs are available. Ten held-out eggs from this collection cannot establish accuracy across farms, batches, lighting conditions, or future camera sessions. Report the count correct for each age and every abstention; do not describe training or validation performance as final-test accuracy.

The deployed automatic flow separately changed to one analyzed JPEG per egg in commit `8025ba2`. Physical accuracy remains under investigation.

The user confirmed that the autonomous holder still rotates and has no separate motor switch. A temporary serial RTS reset hold on the identified CP210x motor adapter did not stop it, according to the user. The hold was released, the port closed, and no motor firmware was written. Earlier scan evidence and the quarantined pilot images were acquired with rotation. A stationary-holder claim is unsupported.
