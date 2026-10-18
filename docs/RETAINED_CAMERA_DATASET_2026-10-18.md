# Camera scans added to the retained dataset

All 30 numbered camera scans were added to a versioned extension of the retained `selective-v2` dataset. The extension contains the original 2,061 historical rows unchanged plus 30 camera rows, for 2,091 images. Images are not counts of independent historical eggs.

The dataset is `data/local/retained-camera-20261018/manifest.jsonl`, with integrity and provenance in `audit.json`. Camera image bytes are preserved under `images/`. They are the prepared live camera frames; there is no extra crop, exposure adjustment, relabeling, or synthetic augmentation. The original dataset, deployed weights, and completed pilot evidence remain unchanged.

## Partition and provenance

| Camera partition | Day 16 | Day 18 | Purpose |
| --- | --- | --- | --- |
| Training | 5 | 5 | Included in the retained model's new training run |
| Validation | 5 | 5 | Model selection and uncertainty calibration |
| Test | 5 | 5 | Preserved completed pilot test; not reopened or used for fitting |

Each camera row carries its physical egg ID, original capture metadata, image hashes, user-reported age, and capture session. The user reports uncooked farm eggs with confirmed incubation dates. Actual incubation records, species verification, and batch IDs have not been supplied, so those fields remain unknown. The collection is not batch-disjoint evidence. Ten stale or unverified early captures remain excluded.

The importer verifies the historical manifest, original camera records, duplicate image identities, cross-partition identities, and copied bytes. The training loader checks the original partition assignments and never reads the reserved camera test images for fitting or scoring.

## Retained-model adaptation

`ml/balut_ml/retained_camera.py` reuses the retained DINOv2 plus EfficientNet encoder and three-class logistic architecture (`C=100`, balanced classes). Training includes 50 Day 16, 62 Day 18, and 1,419 retained Reject examples: 1,531 training images total. Ten of these are the new camera training eggs; all ten pass the existing image-quality checks.

Before fitting, the experiment fixed three camera sample weights: 1, 5, and 20. Weight changes influence fitting; they do not create additional eggs or validation evidence. Selection prefers no historical macro-F1 regression, then camera balanced accuracy, then historical macro F1, with the first candidate breaking ties. None avoided historical macro-F1 regression; weight 20 had the best remaining selection score. Existing quality and novelty limits are retained; decision margins are calibrated on historical and camera validation only.

| Validation result | Retained model | Adapted candidate |
| --- | --- | --- |
| Camera raw age correct | 6/10 | 8/10 |
| Camera Day 16 raw correct | 1/5 | 4/5 |
| Camera Day 18 raw correct | 5/5 | 4/5 |
| Camera accepted correct results | 0/10 | 7/10 |
| Camera wrong accepted results | 0 | 0 |
| Camera review/recapture requests | 10/10 | 3/10 |
| Historical raw correct | 361/368 | 358/368 |
| Historical raw macro F1 | 0.870270 | 0.812500 |

The candidate's 7/7 accepted camera results are validation results at 70% coverage. They do not establish 99% accuracy across all eggs. The validation data also selected and calibrated the candidate. There is no fresh test score for this adaptation; the earlier binary pilot's 10/10 result belongs to that original locked model only.

## Saved artifacts and decision

The run is `ml/runs/retained-camera-20261018/`. It contains the learned three-class `head.npz`, combined training references, uncertainty policy, encoder reference/configuration, experiment plan, selection lock, per-egg validation outcomes, and metrics. It requires the existing verified retained encoder. It is not an activated serving release.

**The dataset addition and retraining are complete. The 99% target is not established.** The adapted candidate improves camera validation but regresses historical validation. Keep the active release and the separate locked binary pilot unchanged. Both historical and original camera tests remain closed.

To reproduce in a fresh checkout with the source artifacts available, use PowerShell from the repository root:

```powershell
$env:PYTHONPATH = 'ml;apps/edge_api'
.venv-ml/Scripts/python.exe -m balut_ml.retained_camera import
.venv-ml/Scripts/python.exe -m balut_ml.retained_camera train
```

Both stages refuse to overwrite completed output. Dataset images and learned artifacts stay local in the repository's ignored data/run directories. No dataset images or candidate weights are published by a Git push.

Verification passed: 13 importer, partition, historical-local-data, and uncertainty-calibration tests; hashes for all 30 imported images; all ten validation decisions reproduced from the saved head, references, and policy; active model known-answer checks; and unchanged protected retained-release and original pilot files. The verification performed no test-set inference. Results are saved in the adaptation run's `verification.json`.
