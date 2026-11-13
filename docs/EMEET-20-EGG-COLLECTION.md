# EMEET collection: 20 eggs, 6,000 age images

Use ten operator-identified eggs of each age. IDs 01–06 train the model, 07–08 select the checkpoint and thresholds, and 09–10 are reserved for physical testing. Keep IDs and eggs together. Do not count a second view or a repositioned egg as a new egg. Check the egg's actual incubation age again if collection spans multiple days. The earlier 29-egg plan is inactive.

Capture 150 different camera frames in each of two physical placements per egg. Between placements, roll the egg about a quarter turn so a different area touches the holder. Keep the lighting and camera geometry consistent between classes. Confirm that the egg itself turns; motor steps alone cannot establish that. Each placement must include at least one turn and images in all 12 estimated angular sectors. These are estimates from the motor counter, not measured egg angles.

The study directory is `data/local/emeet-20-rotation-20261107`. Its frozen plan governs capture and training. The two eggs already started under the larger plan kept their original image content, physical IDs, and training assignments. Their new capture records list the original files and checksums. The preserved Reject manifest references the original Reject images in place. Only its training and validation groups enter model development.

For a confirmed placement, use the serving Python environment and `scripts/capture_rotating_emeet.py EGG_ID side-A` or `side-B`. Inspect the 12-sector review before moving the egg. Failed or incomplete sessions do not become training examples. Keep the four reserved eggs untouched until model selection and calibration finish.

After the 12 training eggs and four validation eggs are complete:

1. Run `ml/balut_ml/train_emeet_mobilenetv2.py` with the study directory and a **new** run directory, `ml/runs/emeet-20-rotation-20261107`, using the ML Python environment. Use 50 maximum epochs and patience 8. Keep the actual training curves, checkpoint, and validation metrics.
2. Run `scripts/seal_emeet_candidate.py` with the same directories. Run `scripts/prepare_emeet_rotation_study.py --physical-protocol` to bind the fresh physical trials to the locked model.
3. For each reserved egg, collect its two dataset placements. While it remains in the holder, run `scripts/repeat_emeet_candidate.py DATASET --study ml/runs/emeet-20-rotation-20261107-physical --egg EGG_ID`. The model scores new camera acquisitions, not the 300 stored images. Finalize the collection manifest with `scripts/prepare_emeet_study.py DATASET --finalize` after all four reserved eggs are collected.

Report the first scan of each reserved egg as the primary result, with wrong, unclassified, and acquisition failures counted as unsuccessful. Show repeatability separately across ten attempts per egg. Two Day 18 test eggs cannot establish performance across a production population. No physical Reject eggs were supplied, so physical Reject recall is unmeasured.
