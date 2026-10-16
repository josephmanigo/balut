# Data needed to measure accuracy on the actual Balut candler

The public experiments measure agreement with three separate sources. The Day 16/18 source does not document species or incubation timestamps, and none of these sources identifies physical eggs. Better public-source scores do not resolve those gaps.

Use the intended duck eggs, camera, light source, egg position, and enclosure. Save the original images before applying contrast changes. Capture the eight views used by this project and keep their capture order. Document camera and lighting settings so later captures can reproduce them.

Record the following alongside every original image, using the blank [capture log](../data/templates/real-candling-capture-log.csv):

- A permanent physical egg ID and incubation batch ID. The same egg keeps its ID at every age and angle.
- Confirmed species, incubation start time, capture time, and timezone. Calculate elapsed incubation hours from these records; do not infer age from appearance or filenames.
- Inspection/frame IDs, view index, angle, original image path, and SHA-256. These map to the existing physical-data manifest schema.
- Camera/candler IDs, capture session, and settings. Record any exposure or positioning problem.
- The proposed appearance label, its authority, reviewer evidence references, and whether it remains unresolved. A community `Reject` label or model prediction is insufficient evidence for a local reject label.

Assign complete batches to train, validation, or prospective test before fitting. Keep every view, crop, augmentation, and later-day capture of an egg in the same partition. Reserve a later capture batch for the prospective test and keep it unused during model/threshold selection. Several photographs of one egg are one physical specimen, not several independent validation examples.

The CSV is a collection worksheet, not an accepted training manifest. Leave unavailable facts blank and unresolved cases out of supervised training. After review, convert accepted records to `DatasetFrame` JSONL using the existing [schema](../ml/balut_ml/dataset.py); place extra species, capture, and device metadata in a linked provenance record because the strict schema rejects extra fields. Audit the resulting manifest before training:

```powershell
$env:PYTHONPATH = 'ml'
.\.venv-ml\Scripts\python.exe -m balut_ml.cli audit-manifest data\verified-manifest.jsonl
```

Report accuracy and abnormal/reject recall at the egg/inspection level, with the number of independently held-out eggs and batches. Report review coverage separately. Use the project's existing study and release criteria to set the required sample size and acceptable error rates before opening prospective-test results; no sample count guarantees an accuracy percentage.
