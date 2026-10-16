# Automatic classification with recapture

The current Windows image workflow has no mandatory human review step. One uploaded candling JPEG produces Day 16, Day 18, suspected Reject, or **Another image needed**. An unclear image is saved with `sourcePrediction=null`, `analysisOutcome=RECAPTURE_REQUIRED`, `recaptureRequested=true`, and `reviewRequired=false`. It is not assigned a class. A replacement image can be analyzed normally; repeated uncertainty leaves it unclassified. There is no attempt limit that forces a guess.

The software requests a replacement image. With no physical candler/camera connected, the operator selects a new JPEG. Automatic camera acquisition and physical sorting are not implemented by this release.

## Measured result: 100% was not achieved

The fixed historical public test contains 172 images. With the frozen quality, score-margin, and feature-distance gates, **97 were classified, 95 correctly and 2 incorrectly; 75 requested recapture**. Accepted accuracy is **97.94%**, classification coverage is **56.40%**, and correct classifications as a fraction of all inputs are **55.23%**. The two accepted errors were source-labelled Day 16 images predicted as Day 18.

| True public-source label | Images | Correct classification | Wrong classification | Unclassified / recapture |
|---|---:|---:|---:|---:|
| Day 16 | 15 | 8 | 2 | 5 |
| Day 18 | 20 | 13 | 0 | 7 |
| Reject | 137 | 74 | 0 | 63 |
| Total | 172 | 95 | 2 | 75 |

Among issued predictions, Day 16 was correct 8/8, Day 18 13/15, and Reject 74/74. These small, source-confounded counts do not guarantee correctness on another egg. The gates blocked four of six raw-model mistakes and also withheld 71 correct raw predictions. Recapture reasons can overlap: 65 blur flags, 11 ambiguity flags, five unfamiliar-appearance flags, and five small-image flags.

Before abstention, the new classifier was correct on 166/172 images (96.51%), with balanced accuracy and macro F1 both 0.8833. Day 16 recall improved from 8/15 in the prior three-class model to 12/15; Day 18 changed from 19/20 to 17/20; Reject remained 137/137. The overall figure is dominated by Reject and should not be interpreted as that level of age accuracy.

The validation-selected gate had zero observed errors on 211 accepted validation images out of 368. That development result was **not** reproduced perfectly on historical test images. No model or threshold was adjusted after observing the test result to make a perfect score.

## Data and bounded training experiment

The same audited partitions from `ml/runs/three-class-v1/manifest.jsonl` are preserved: training 45 Day 16, 57 Day 18, and 1,419 Reject; validation 16, 20, and 332; historical test 15, 20, and 137. No additional images were claimed or labels invented for this experiment. Public sources are [THESIS Egg Candling v6](https://universe.roboflow.com/thesis-mwxui/egg-candling-bdezy/dataset/6) and [Pat Balut Eggs Project v8](https://universe.roboflow.com/pat-bteu2/balut-eggs-project-unfertilized-fertilized-and-reject-tgibj/dataset/8); their exported CC BY 4.0 notices are included with the sealed release. Pat Fertilized and Unfertilized are excluded from this classifier.

Forty-eight candidates compared DINOv2 features alone and fusion with ConvNeXt-Tiny or EfficientNet-B0, using logistic or RBF heads. Only training features fit the heads; validation macro F1, balanced accuracy, then accuracy chose the winner. The selected model combines frozen DINOv2 ViT-S/14 and EfficientNet-B0 features with a balanced logistic head, C=100. Original and horizontally flipped features are averaged and normalized per backbone; concatenated features are divided by sqrt(2).

Per-class raw-score margins were set above all observed validation mistakes, requiring at least five accepted examples. Nearest same-class training cosine thresholds use the first percentile of validation similarities. Image heuristics require at least 64 pixels on the short side, grayscale standard deviation 8, fixed-scale Laplacian variance 20, and clipped-pixel fraction at most 0.85. These are development heuristics, not calibrated confidence probabilities or validated optical acceptance limits.

The selected model and thresholds were locked before the new historical test evaluation. This holdout has been inspected in earlier experiments and is not an independent prospective test. Selecting further changes from its errors would overstate generalization; see [scikit-learn's guidance on test-data leakage](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage).

**The data cannot establish real candler accuracy.** Day labels have no independently verified incubation timestamps or species. Physical egg/session IDs are missing. Reject comes from a different collection than the age labels, so recognizing the collection's lighting or background can inflate Reject results. Reject labels are not verified spoilage or food-safety outcomes. A useful next accuracy experiment needs identified eggs of all three classes captured with the same candler, verified ages/label evidence, and fresh eggs/sessions reserved for evaluation. Training on these public images repeatedly cannot supply those missing facts.

## Software verification and provenance

- The sealed release is `deployment/releases/automatic-recapture-20260912`, with default model `egg-grade`.
- Registry SHA-256: `3a0b30b6f675e7bf07e12cdaa0e7c7cbd1c79ba3f4f4c65f665d7fd4f52c9c87`.
- ONNX SHA-256: `21becfa01438ce8fc89dd232eee6c3b1a029e8938ce81a60df0de9386c0651bd`.
- Selection lock SHA-256: `3d7d5a4cb6b819de8fe28f4ca44872fc73249eb2e4f1375082ea8cfdebfce62e`.
- Model, config, gate policy, training references, and startup fixture hashes are checked. Removing, changing, or mismatching the recapture artifacts stops startup. Accepted classes remain appearance predictions; `operationalUseAuthorized=false` and `operationalOutcome=NOT_AUTHORIZED` refer to physical grading authority, not a human review requirement.
- CPU PyTorch/ONNX maximum score difference was 0.0000211 and feature difference 0.000000797. All 172 raw predictions and all class/recapture decisions agree with the frozen GPU results. A larger GPU numerical difference is retained in `onnx-gpu-parity.json`; no model or gate was changed to resolve it.
- 72 API/core checks passed, five optional training checks skipped in the serving environment, two upstream deprecation warnings. Ten focused ML tests passed in the training environment. Eight web tests and the TypeScript/Vite build passed. Suites overlap and are not summed as distinct tests.
- Real ONNX API and built Edge browser tests covered all three predicted classes, a dark image, an ambiguous candling image, no dropdown, no mandatory review label, desktop/mobile rendering, and replacement-image behavior. Five known fixture inference times were 128–132 ms on this laptop; this is a small software check, not a production latency benchmark.
- The isolated live test preserved 15 prediction/recapture records and five evidence images across process termination, restart, backup, restore, and restored-service retrieval. It checked authentication, invalid JPEG rejection, replay idempotency, and that each owned test listener stopped before restart.

Evidence: `artifacts/selective-api-tests.xml`, `selective-ml-tests.xml`, `selective-web-verification.log`, `selective-live-verification.json`, `selective-ui-verification.json`, and `ml/runs/selective-v2/metrics.json`.

## Test without the physical candler

Open Chrome or Edge on this laptop at `http://127.0.0.1:8765` and sign in as `operator` using `scripts/Copy-Balut-Login.ps1`. The credentials are unchanged and are never included in the ZIP. Codex's embedded browser can block this local address. After reboot, run `scripts/Start-Balut.ps1 -Supervise` and leave it running.

Upload files from `data/recapture-test-samples` using the same Analyze egg button:

| File | Expected software behavior |
|---|---|
| `day_16.jpg` | Day 16 |
| `day_18.jpg` | Day 18 |
| `reject.jpg` | Reject — suspected |
| `too-dark.jpg` | Another image needed; unclassified |
| `unclear-egg.jpg` | Another image needed; unclassified |

After recapture is requested, select a replacement JPEG. The button stays disabled for the current unclear image to avoid rerunning the same request automatically. These known-answer files test software installation; they are selected validation examples and a synthetic dark image, not a new accuracy test.

The handoff is `artifacts/balut-automatic-recapture-20260912.zip`. See [the Windows operating guide](WINDOWS_MODEL_SERVICE.md) for offline installation and backup. This is tested Windows image-analysis software with abstention. The model has not achieved 100% accuracy, and autonomous physical grading has not been validated.
