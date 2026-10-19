# Reject captures before retained-model retraining

The operator requested 50 paused camera photos of each of three additional Reject eggs before retraining. All three are reported uncooked and unmarked. The vendor supplied them as Reject eggs without giving a rejection reason; the labels are recorded as vendor reports, not independently confirmed defects.

R1 is training, R2 validation, and R3 reserved test. These assignments are fixed before capture. The same motor hold, fresh-frame, CRC, JPEG, quality, duplicate-image, and distinct commanded-bin checks used for the completed 30-egg collection are reused. No model labels or selects the photos. Physical angles remain approximate because the holder has no encoder.

`scripts/capture_reject_sweep.py R1` captures one operator-confirmed egg. `--resume` requires the same egg to stay undisturbed with the spinner powered. The automatic cloud connector must be stopped while collection owns the USB ports. Captures and the sealed collection plan are under `output/physical-reject-20261019`. The shared importer verifies the plan, vendor provenance, image identities, original dataset prefix, and fixed partitions before adding photos.

The expanded dataset is `data/local/retained-camera-rejects-20261019`. Its base preserves all 3,681 previous rows, including the earlier 90 multiangle views and the 1,500 new age views. Completion requires 150 additional Reject views, giving 3,831 rows total. The dataset audit remains `COLLECTION_IN_PROGRESS` until all three Reject eggs have 50 views.

`balut_ml.train_camera_sweep` refuses incomplete collection. It reuses the retained encoder and historical training features, fits three predeclared three-class logistic heads with C=100 and total camera weight 20, 50, or 100 per physical egg, and distributes each egg's weight across its views. Only the 11 camera training eggs fit the head. The 11 validation eggs select the candidate; all 11 test eggs remain excluded from fitting and inference.

Validation compares against the actual active camera head with unchanged uncertainty and quality thresholds. For each 50-view validation egg, 16 disjoint three-view groups use commanded bins i, i+17, and i+34 for i=0 through 15. Bins 16 and 33 remain in per-image reporting. These groups are correlated scans of the same egg, not independent eggs. Reports also compare the earlier three-view groups, original single frames, and retained historical validation.

Admission requires more correctly accepted new scans without per-class raw, accepted-correct, wrong-acceptance, or coverage regression; at least half of scans for each class must be correctly accepted. Earlier camera and retained historical validation must not regress. A failed candidate is saved and cannot replace the active model. Retraining and these development comparisons do not establish 99 percent accuracy; Reject validation has only one independently numbered egg and no confirmed rejection reason.

## Completed collection and retraining

All three Reject eggs completed 50 views. The final manifest contains 3,831 rows and has SHA-256 `2ce212014705768fbf4978e00e37cc9dff24daa08d851df7e5be086ba07c61d1`. All 90 earlier multiangle views, 1,500 age sweep views, and 150 Reject views are included. The original 3,681-row dataset is preserved. There are 33 numbered physical eggs, with 11 in each partition.

Retraining completed in `ml/runs/retained-camera-50views-rejects-20261019`. The head used 590 eligible camera training views from 11 eggs plus 1,521 retained historical training examples: 315 Day 16, 327 Day 18, and 1,469 Reject rows. Of the 1,740 newly requested photos, 580 belong to training, 580 to validation, and 580 to reserved test. The ten original age training frames supply the other ten camera training views. Reserved test images were not opened for model inference.

All three candidate weights failed admission. Weight 100 selected the best saved development candidate, but it still performed worse than the actual active camera head:

| Same 176 correlated scan groups from 11 validation eggs | Current camera head | Retrained candidate |
| --- | ---: | ---: |
| Correctly classified | 153 | 129 |
| Wrongly classified against supplied labels | 16 | 16 |
| Requested another scan | 7 | 31 |
| Raw correct before uncertainty gates | 160 | 157 |

The current and retrained heads each misclassified all 16 scan groups from the single vendor-labeled Reject validation egg. On the age eggs, the current head correctly accepted 75/80 Day 16 and 78/80 Day 18 groups; the candidate accepted 72/80 and 57/80 respectively. The earlier ten three-view validation groups declined from 10 correctly classified to six. Retained historical raw validation declined from 359/368 to 356/368 and gained two wrongly accepted predictions. These findings describe this development comparison against the recorded labels, not verified biological performance.

The candidate, references, experiment plan, outcomes, metrics, and artifact hashes are saved. The active app model was not replaced because none of the retrained candidates passed the fixed checks. More repeated views did not improve this experiment's validation results.
