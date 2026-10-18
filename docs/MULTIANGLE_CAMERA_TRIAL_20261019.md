# Three-angle camera trial, 19 October 2026

The experimental app release is `camera-multiangle-trial-20261019`. Each automatic scan uses three fresh camera views. The local USB connector holds the identified spinner for each capture, resumes it between views, waits approximately 683 commanded motor steps, and resumes it before uploading the group. The operator confirmed visible pauses and rotation between captures during numbered collection. Motor steps are approximate spacing, not measured angles.

## Data and model

All 30 numbered eggs have three additional verified JPEG views: 90 new images. `data/local/retained-camera-angles-20261019/manifest.jsonl` contains 2,181 rows, preserving the original 2,091 rows. Views retain each egg's original physical ID and partition. Ten eggs remain training, ten validation, and ten previously tested eggs stay closed. Repeat photos do not increase the independent egg count. The user supplied the cohort ages and reported farm incubation dates; current elapsed incubation records are not supplied.

The frozen encoder is unchanged. The linear head was fitted using the retained training data plus the 40 camera training images from ten eggs, with each egg's weight distributed across its views. One fixed candidate and one subsequent conservative development calibration are preserved separately. The calibration only increased the Day 18 decision margin, from 2.6856889588928223 to 6.192462308502197.

Neither candidate qualified as a global replacement: the first wrongly accepted one historical validation image, and the calibrated version reduced historical correct acceptance from 212 to 208 of 368 images. Those failures remain recorded in their original runs. They are not overwritten or relabeled as successes.

## Serving contract and checks

The camera-only trial keeps the previous ONNX classifier, gate policy, reference bank, and software fixtures byte-identical for single-photo requests. Only three-view analysis uses the sealed new camera head and its calibration. The registry seals the head, policy, references, and known-answer fixtures. Results record both encoder/model and camera-head hashes. Distinct-view consensus still requires at least two accepted agreeing views; any accepted class conflict requests another scan. Quality, unfamiliar-image, and ambiguity gates remain active.

`scripts/prepare_multiview_trial.py` records the revised serving contract before checking it. It verifies the frozen source artifacts, checks all 40 camera validation views through unchanged single-photo inference, compares the 30 new camera validation views with the frozen calibrated outputs, and verifies all ten groups through the actual three-view service. It does not refit, select another threshold, or open the closed test eggs.

| Development validation, ten eggs | Previous head with three-view consensus | Camera-only trial |
| --- | ---: | ---: |
| Correct accepted eggs | 6/10 | 10/10 |
| Wrong accepted eggs | 0 | 0 |
| Coverage | 60% | 100% |
| Day 16 correct accepted | 1/5 | 5/5 |
| Day 18 correct accepted | 5/5 | 5/5 |

These are development results after calibration, not a fresh independent accuracy test. They do not establish 99% performance on new eggs or batches. The old retained release and the previous camera trial remain available. Model chunks are unchanged because the encoder/ONNX file is unchanged.

## Limits and live acceptance

The release remains an experimental appearance classifier with no physical grading or food-safety authority. Corrupt or incomplete USB frames are discarded and retried; intermittent transport failures remain under investigation. The Windows connector allocates a receive buffer large enough for complete frames; this does not eliminate observed corruption. Confirmed-empty calibration has a 45-second deadline and tolerates preview gaps within that deadline for the same signed motor-camera session. It still requires three fresh matching frames, cancels on camera/framing changes, and expires without enabling analysis when no steady view is obtained. A successful software check or motor ACK alone does not prove physical pauses in the deployed path. Confirm the deployed registry and save fresh live results from one known egg of each age, checking three distinct views and visible stop/resume behavior.

Artifacts: the complete dataset audit is `data/local/retained-camera-angles-20261019/audit.json`; the failed global runs are `ml/runs/retained-multiangle-20261019` and `ml/runs/retained-multiangle-calibrated-20261019`; the camera-only serving report is `deployment/releases/camera-multiangle-trial-20261019/verification.json`.
