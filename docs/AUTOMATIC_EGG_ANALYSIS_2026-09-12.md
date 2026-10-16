# Automatic Day 16 / Day 18 / Reject analysis

The operator uploads one candling JPEG and presses **Analyze egg**. A single trained three-class model chooses **Day 16**, **Day 18**, or **Reject — suspected**. The model selector has been removed. The server chooses the model from its checksum-pinned release; changing a filename or a browser value cannot choose the grade.

Predictions remain subject to human confirmation. Chronological age comes from incubation records. A Reject prediction is a reason for review, not proof that an egg is rotten. This release performs image analysis; it does not operate or authorize physical sorting.

## Use on this laptop

1. Run `scripts/Copy-Balut-Login.ps1` in PowerShell.
2. Open Chrome or Edge on the Windows laptop and paste `http://127.0.0.1:8765` into the address bar. Sign in as `operator` with the copied password. Clear the clipboard after signing in. Codex's embedded browser can block this local address.
3. Open **Analyze egg**, choose a JPEG cropped around one egg, and press **Analyze egg**. There is no comparison-model dropdown.
4. Read the predicted class and expand **Saved prediction record** for its ID and timestamp. Repeating the same unchanged request reuses that record.

After reboot, run `scripts/Start-Balut.ps1 -Supervise` and leave the PowerShell window running. The service is local to this laptop.

## Software samples

Use `data/automatic-test-samples/day_16.jpg`, `day_18.jpg`, and `reject.jpg`. All three use the same Analyze button. Their expected model outputs are DAY_16, DAY_18, and REJECT respectively. They are validation fixtures selected to check installation, not a new accuracy test. `manifest.json` records source identity and hashes. The older `data/software-test-samples` folder belongs to the prior separate-model interface.

## What was trained

The training job combines the already audited age crops with only the Pat source's explicit Reject crops. Pat Fertilized and Unfertilized images are not assigned an age or relabelled as Reject. Original train/validation/test partitions are preserved. Combined-source SHA-256, pixel hashes, and near-duplicate checks ran before selection; no cross-source near-duplicate conflicts were found.

| Partition | Day 16 | Day 18 | Reject |
|---|---:|---:|---:|
| Train | 45 | 57 | 1,419 |
| Validation | 16 | 20 | 332 |
| Historical test | 15 | 20 | 137 |

Forty-two frozen-feature classifiers were compared using only validation macro F1, then balanced accuracy and accuracy. The selected model is EfficientNet-B0 with a fitted classification head. The selection was locked before the unified model's historical test evaluation. This test set was previously examined in the separate experiments; it is not a new untouched field evaluation.

| Historical result | Correct / total | Recall |
|---|---:|---:|
| Day 16 | 8 / 15 | 53.3% |
| Day 18 | 19 / 20 | 95.0% |
| Reject | 137 / 137 | 100% |
| Overall | 164 / 172 | 95.3% accuracy |

Balanced accuracy is **82.8%**, and macro F1 is **0.831**. Seven Day 16 images were predicted as Day 18; one Day 18 image was predicted as Day 16. Overall accuracy is dominated by the much larger Reject class and must not be read as 95% Day 16 accuracy.

**Reject is confounded with dataset source:** the Reject images come from a different collection than the age images. The model may recognize that collection's appearance. The perfect historical Reject result does not establish reliable rejection on a real candler. Species, physical egg IDs, verified incubation times, and independent rejection ground truth are unavailable. New identified eggs from the same real capture setup are needed for a valid combined evaluation.

The export compared all 172 historical test crops across the fitted GPU reference, CPU PyTorch, and ONNX. All predicted classes agreed; maximum CPU/ONNX score difference was below 0.000003. Output scores are uncalibrated decision scores, not confidence percentages.

## Implementation and verification

- Model: `ml/runs/three-class-v1`; training command: `python -m balut_ml.train_three_class --output <fresh-directory>` with `PYTHONPATH=ml`.
- Release: `deployment/releases/automatic-three-class-20260912`; default analysis model: `egg-grade`.
- API: `POST /api/v1/egg-analysis`, authenticated raw JPEG with `X-Balut-Origin: local` and `Idempotency-Key`. The request has no user-selected class or model parameter.
- API result: `sourcePrediction` is DAY_16, DAY_18, or REJECT; `reviewRequired=true`, `operationalUseAuthorized=false`, and `operationalOutcome=REVIEW_RECAPTURE` preserve the operational boundary.
- Records retain the pinned model and registry hashes, image evidence, audit entry, and replay identity.
- The original model-specific API remains available for technical regression checks. The operator page uses only the unified endpoint.

Current automated results are in `artifacts/automatic-api-tests.xml`, `automatic-ml-tests.xml`, `automatic-web-verification.log`, `automatic-live-verification.json`, and `automatic-ui-verification.json`. Older production reports describe the prior release. Backup/restore procedures are in [the Windows operating guide](WINDOWS_MODEL_SERVICE.md).
