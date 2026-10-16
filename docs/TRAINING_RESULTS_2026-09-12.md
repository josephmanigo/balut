# Balut public-dataset training results — 2026-09-12

Three MobileNetV3-Small classifiers were trained locally on the RTX 3080. These are exploratory source-label models; no operational model release was created.

The Day 16/18 experiment is too weak for reliable age decisions, and its source does not document duck species. The duck-status model also misses abnormal examples despite high overall accuracy. Preserve the review workflow.

| Model | Train / validation / test | Test accuracy | Balanced accuracy | Macro F1 | Selected epoch |
|---|---:|---:|---:|---:|---:|
| Duck candling status | 831 / 67 / 87 | 95.4% | 90.5% | 0.926 | 23 |
| Source-labelled Day 16 vs Day 18 | 102 / 36 / 35 | 62.9% | 60.0% | 0.596 | 2 |
| Pat source-labelled Fertilized / Reject / Unfertilized | 4077 / 636 / 461 | 94.1% | 94.3% | 0.921 | 9 |

Counts are images or annotated egg crops, not independent physical eggs. Selection used validation loss; test predictions were computed only after checkpoint selection. No test result was used to select a later checkpoint.

## Duck candling status

[Model card](../ml/runs/duck-candling-v1/model-card.md) · [PyTorch weights](../ml/runs/duck-candling-v1/best.pt) · [ONNX weights](../ml/runs/duck-candling-v1/best.onnx) · [Metrics](../ml/runs/duck-candling-v1/metrics.json)

Source: [Duck Egg Candling - Team DevIn / ryleanthony-gabotero](https://universe.roboflow.com/ryleanthony-gabotero/duck-egg-candling/dataset/2). Retained 985 images/crops. Exclusions: `{"image_group_overlaps_higher_priority_holdout": 410}`.

[Dataset audit](../data/public/duck-egg-candling/audit-v2/audit.json) · [Inspected sample sheet](../data/public/duck-egg-candling/audit-v2/contact-sheet.jpg)

## Source-labelled Day 16 vs Day 18

[Model card](../ml/runs/source-age16-18-v1/model-card.md) · [PyTorch weights](../ml/runs/source-age16-18-v1/best.pt) · [ONNX weights](../ml/runs/source-age16-18-v1/best.onnx) · [Metrics](../ml/runs/source-age16-18-v1/metrics.json)

Source: [THESIS - Egg Candling, version 6](https://universe.roboflow.com/thesis-mwxui/egg-candling-bdezy/dataset/6). Retained 173 images/crops. Exclusions: `{}`.

[Dataset audit](../data/public/thesis-egg-candling/audit-v1/audit.json) · [Inspected sample sheet](../data/public/thesis-egg-candling/audit-v1/contact-sheet.jpg)

## Pat source-labelled Fertilized / Reject / Unfertilized

[Model card](../ml/runs/pat-balut-v1/model-card.md) · [PyTorch weights](../ml/runs/pat-balut-v1/best.pt) · [ONNX weights](../ml/runs/pat-balut-v1/best.onnx) · [Metrics](../ml/runs/pat-balut-v1/metrics.json)

Source: [Pat - Balut Eggs Project, version 8](https://universe.roboflow.com/pat-bteu2/balut-eggs-project-unfertilized-fertilized-and-reject-tgibj/dataset/8). Retained 5174 images/crops. Exclusions: `{"image_group_overlaps_higher_priority_holdout": 3442}`.

[Dataset audit](../data/public/pat-balut/audit-v2/audit.json) · [Inspected sample sheet](../data/public/pat-balut/audit-v2/contact-sheet.jpg)

## Run a prediction locally

Use a single-egg candling image. For the age and Pat models, crop the egg first, matching training. The duck-status model used the full published image framing.

```powershell
.\scripts\Predict-Candling.ps1 -ImagePath "C:\path\to\egg.jpg" -Model duck-status
.\scripts\Predict-Candling.ps1 -ImagePath "C:\path\to\egg-crop.jpg" -Model age16-18
.\scripts\Predict-Candling.ps1 -ImagePath "C:\path\to\egg-crop.jpg" -Model pat-status
```

These commands return original source labels and uncalibrated probabilities. The operational outcome remains REVIEW_RECAPTURE. No production API, simulator, firmware release, or physical grading authority was changed.

The original archives and their README/license files remain under data/public. Training source, exact manifests, epoch histories, test predictions, checkpoints, and ONNX parity results are retained for audit. The two first experiments used conservative dHash/filename grouping. Pat uses filename grouping plus dHash and RGB similarity because grayscale hashes alone falsely match different egg silhouettes.
