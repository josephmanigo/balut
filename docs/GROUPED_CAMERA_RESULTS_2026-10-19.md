# Grouped camera improvement experiment - 2026-10-19

The new raw classifier improved historical image accuracy from **84.75% to 88.14%**, and macro F1 from **88.50% to 91.04%**. It was **not promoted**: recapture coverage fell from 68.41% to 48.54%, and correct classifications over all inputs fell from 65.18% to 48.54%. The active web/mobile backend remains `unfertilized-trial-20261019`.

## What changed

The existing dataset is unchanged. Its 3,070 training/validation development images were pooled for five-fold grouped cross-validation, allowing the final classifier to fit all twenty development age eggs. Ten historical age eggs remained excluded from fitting. Each fold held out two physical eggs per age, with every view of each egg and every recorded public image family kept together.

All development embeddings were recomputed with the actual ONNX CPU image pipeline: native camera JPEG bytes, or public PNG converted to RGB JPEG quality 95. Original files and labels remain unchanged. Reject is the requested name for source Unfertilized annotations. R1/R2/R3 remain excluded.

Eighteen linear settings were compared using three retained feature views, three regularization values and two camera weights. A bounded six-setting RBF comparison then used the same locked development folds. Neither comparison opened historical test images. Selection prioritized physical-egg recall, weaker-age recall, worst camera-fold recall, then public-source macro F1.

The selected model uses retained frozen DINOv2 ViT-S/14 + EfficientNet-B0 features and three one-vs-rest RBF SVMs, with **C=100, gamma=1** and per-egg view weighting. This is a new classifier fit, not another CNN epoch run. The earlier eleven-epoch image experiment remains archived separately.

## Actual results

| Same-fold camera recall | Linear control | Selected kernel |
| --- | ---: | ---: |
| Day 16 | 88.33% | 89.44% |
| Day 18 | 95.00% | 95.56% |
| Mean | 91.67% | 92.50% |

After all development choices and thresholds were locked, one historical regression evaluated all 649 images through the actual serving model. No fitting or threshold changes followed that evaluation.

| Historical measure | Active model | Candidate |
| --- | ---: | ---: |
| Raw correct | 550/649 | 572/649 |
| Raw accuracy | 84.75% | 88.14% |
| Raw macro F1 | 88.50% | 91.04% |
| Raw Day 16 recall | 87.37% | 93.33% |
| Raw Day 18 recall | 78.28% | 80.00% |
| Correct after gates | 423 | 315 |
| Wrong after gates | 21 | 0 |
| Recaptures | 205 | 334 |
| Coverage | 68.41% | 48.54% |
| Correct / all inputs | 65.18% | 48.54% |

Candidate raw matrix (recorded rows; predicted columns Day 16 / Day 18 / Reject): `[[266,19,0],[58,232,0],[0,0,74]]`.

Candidate gated matrix (last column Recapture): `[[69,0,0,216],[0,189,0,101],[0,0,57,17]]`.

Zero errors among the 315 accepted images does not establish 100% general accuracy. Correct accepted Day 16 outputs decreased from 165 to 69, and Day 18 from 201 to 189. The candidate fails the predefined coverage/per-class usefulness checks. It stays local and inactive.

## Verification and evidence limits

- Eight focused tests pass for feature-head portability, group isolation, quality/unsupported-class recapture, and existing training helpers.
- Portable kernel scores match the fitted models within 0.00000123. Exported CPU scores and embeddings exactly match cached CPU results on a fixed 64-image development sample.
- Serving startup and attached-photo/camera routes pass public-source class fixtures and a synthetic dark-image recapture fixture.
- Original source photos, prior releases, active-release pointer, prediction history, and capture/motor behavior are preserved. Unrelated in-progress web/backend edits are untouched.
- Historical test views represent ten physical age eggs, and the historical set was already inspected in earlier experiments. This is not a new blind field study.
- Public source egg/batch identities and biological Unfertilized status remain incomplete. No fresh eggs were available, and no full live-scan repeatability or 0.5 score-tolerance test was performed.

## Local artifacts

- `output/pdf/EggGrade-IoT-Grouped-Camera-Results-20261019.pdf`
- `output/model-results/EggGrade-IoT-Grouped-Camera-Results-20261019/results.png`
- `output/model-results/EggGrade-IoT-Grouped-Camera-Results-20261019/cross-validation-comparison.png`
- `output/model-results/EggGrade-IoT-Grouped-Camera-Results-20261019/classification-metrics.csv`
- `output/model-results/EggGrade-IoT-Grouped-Camera-Results-20261019/same-egg-single-view-results.csv`
- `output/model-results/EggGrade-IoT-Grouped-Camera-Results-20261019.zip`

Model runs: `ml/runs/grouped-camera-20261019`, `ml/runs/grouped-kernel-20261019`, and `ml/runs/grouped-camera-historical-20261019`. The inactive sealed release is `deployment/releases/grouped-camera-trial-20261019`; its weights and generated reports stay local. Only source and this aggregate explanation are intended for repository review.
