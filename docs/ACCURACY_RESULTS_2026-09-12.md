# Accuracy comparison — 2026-09-12

The second experiment improved source-labelled Day 16/18 accuracy from 62.9% to 82.9%, and Pat status accuracy from 94.1% to 96.5%. The new duck-status candidate regressed from 95.4% to 93.1%; the original checkpoint is preserved. These are historical image/crop test results, not prospective physical-egg or device accuracy.

| Task | Original test correct | Candidate test correct | Original → candidate accuracy | Candidate balanced accuracy | Candidate macro F1 |
|---|---:|---:|---:|---:|---:|
| Duck candling status | 83/87 | 81/87 | 95.4% → 93.1% | 88.6% | 0.908 |
| Source-labelled Day 16 / Day 18 | 22/35 | 29/35 | 62.9% → 82.9% | 82.5% | 0.825 |
| Pat Fertilized / Reject / Unfertilized | 434/461 | 445/461 | 94.1% → 96.5% | 96.3% | 0.952 |

## How the comparison was selected

All three original audited manifests and their train/validation/test partitions were frozen. No labels were changed and no extra test images were removed. Each task compared 42 candidates: three pretrained frozen backbones (DINOv2 ViT-S/14, ConvNeXt-Tiny, EfficientNet-B0), eight L2 logistic-regression settings, and six one-versus-rest RBF SVM settings. The fixed representation averages original and horizontally flipped views, then L2-normalizes the embedding. Only the classifier is fitted to the source training labels.

Selection uses validation macro F1, then balanced accuracy, then accuracy; exact ties keep the first candidate. All three task selections were recorded together before any candidate test features were extracted. The `promoted` field in that selection record means the candidate beat the baseline validation key; it is not a release approval or a claim that test performance improved. No further candidate was chosen after seeing these test results.

The experiment completed locally on the RTX 3080 in 169.0 seconds, excluding ONNX export/verification. [Experiment plan](../ml/runs/accuracy-v2/experiment-plan.json), [selection record](../ml/runs/accuracy-v2/selection-lock.json). Selection record SHA-256: `baebb782a7c5e5833fa16bf46077ba83b734d7fbb7463aec8e34bd5c311b198f`.

The test was already examined in the original experiment, so this is a retrospective comparison on the same historical holdout. It is not a newly blinded acceptance test. The 35-image age set is especially small: one prediction changes its accuracy by 2.86 percentage points. Physical egg identities and batch separation remain unavailable; image-family deduplication cannot establish independent eggs.

## Duck candling status

`dinov2_vits14` + `rbf_ovr`. [Model card](../ml/runs/accuracy-v2/duck-candling/model-card.md) · [PyTorch](../ml/runs/accuracy-v2/duck-candling/best.pt) · [ONNX](../ml/runs/accuracy-v2/duck-candling/best.onnx) · [all validation candidates](../ml/runs/accuracy-v2/duck-candling/candidates.jsonl).

## Source-labelled Day 16 / Day 18

`dinov2_vits14` + `logistic`. [Model card](../ml/runs/accuracy-v2/source-age16-18/model-card.md) · [PyTorch](../ml/runs/accuracy-v2/source-age16-18/best.pt) · [ONNX](../ml/runs/accuracy-v2/source-age16-18/best.onnx) · [all validation candidates](../ml/runs/accuracy-v2/source-age16-18/candidates.jsonl).

## Pat Fertilized / Reject / Unfertilized

`convnext_tiny` + `rbf_ovr`. [Model card](../ml/runs/accuracy-v2/pat-balut/model-card.md) · [PyTorch](../ml/runs/accuracy-v2/pat-balut/best.pt) · [ONNX](../ml/runs/accuracy-v2/pat-balut/best.onnx) · [all validation candidates](../ml/runs/accuracy-v2/pat-balut/candidates.jsonl).

The age candidate correctly classifies 12/15 Day 16 examples and 17/20 Day 18 examples. It still makes six errors in 35 images. Pat Reject recall improved only modestly, from 121/137 (88.3%) to 123/137 (89.8%); fourteen Reject-labelled crops are still missed. Duck abnormal recall remains 10/14 (71.4%), and the new candidate adds two fertile/infertile errors. Overall accuracy must not hide these weaknesses.

## Use the candidate files

From the Balut workspace:

```powershell
.\scripts\Predict-Candling.ps1 -ImagePath "C:\path\to\egg-crop.jpg" -Model age16-18 -Version accuracy-v2
.\scripts\Predict-Candling.ps1 -ImagePath "C:\path\to\egg-crop.jpg" -Model pat-status -Version accuracy-v2
```

Use a single-egg crop for age and Pat status, matching their training images. `-Version baseline` (also the unchanged default) runs the original models. `-Model duck-status -Version accuracy-v2` explicitly selects the new duck candidate, whose historical test result is lower. Every command continues to return `REVIEW_RECAPTURE` for operational grading.

The new ZIP includes all three candidates plus the original duck-status baseline, PyTorch/ONNX files, class orders, scores, all candidate validation results, licenses, and inference code. Run its `predict.py` with an ONNX file using only NumPy, Pillow, and ONNX Runtime; Torch and network access are unnecessary for this inference route.

For further progress on real duck-age accuracy, collect identified eggs from the actual candler with verified species, incubation/capture times, reviewer evidence, and whole-batch holdouts. [Collection guide](REAL_CANDLING_DATA_COLLECTION.md) · [Blank capture log](../data/templates/real-candling-capture-log.csv). No additional real-device accuracy can be claimed until those data exist and are evaluated.
