# Accuracy improvement methods — 2026-09-12

This is a research note and bounded local audit, not a training result. Improved checkpoints and measured scores must be evidenced separately. The recommended first experiment is a stronger frozen image representation with a regularized classifier, followed by a small fine-tuning comparison that keeps BatchNorm statistics fixed. Preserve the existing audited splits and original labels.

## What the local evidence establishes

The [training report](TRAINING_RESULTS_2026-09-12.md) records MobileNetV3-Small test accuracies of 95.4% for duck status, 62.9% for source-labelled Day 16/18, and 94.1% for Pat status. Overall accuracy hides the weaker abnormal/reject recall. The [age audit](../data/public/thesis-egg-candling/audit-v1/audit.json) contains only 102 training crops (45 Day 16 and 57 Day 18), 36 validation crops, and 35 test crops; its `unique_physical_eggs` is null. One additional correct age test prediction changes accuracy by approximately 2.86 percentage points.

The current [trainer](../ml/balut_ml/train_public.py) freezes the feature extractor and its BatchNorm statistics during the first three epochs. From epoch four, `model.train()` resumes BatchNorm running-statistic updates while feature weights are fine-tuned. This is an experimental choice to compare, not evidence of a coding defect or the proven cause of poor age accuracy.

## Practical experiment order

1. **Compare frozen representations first.** Extract deterministic pretrained features, then fit L2 logistic regression or a linear SVM. The PyTorch tutorial explicitly supports fixed feature extraction as a transfer-learning route. With the tiny age training pool, restricting the fitted parameters to a shallow classifier is a reasonable project-specific way to test whether full-network adaptation is overfitting; improvement is not guaranteed. Use the same image framing at training and inference. [PyTorch transfer-learning tutorial](https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html)

2. **Include DINOv2 ViT-S/14 as one representation candidate.** Meta's official repository provides pretrained `dinov2_vits14` and `dinov2_vits14_reg` backbones, linear evaluation code, and weights under Apache 2.0. Its existence and general-purpose evaluation support trying a frozen-feature classifier; they do not establish candling performance. Pin the code revision, checkpoint hash, transform, and feature pooling in the run manifest. A small backbone is a practical first comparison on the available GPU; memory/latency must be measured locally. [Official DINOv2 code and models](https://github.com/facebookresearch/dinov2)

3. **Keep the classifier search small and regularized.** Try a preregistered short logarithmic grid such as `C = 0.01, 0.1, 1, 10`, with optional class weighting. Lower `C` gives stronger logistic-regression regularization. For SVMs, use feature standardization and compare linear before considering an RBF kernel. Class weighting can trade precision against recall; it does not guarantee a better overall score. Choose with validation balanced accuracy/macro F1 and the relevant abnormal/reject recall, with a declared tie-breaker, before evaluating test. [LogisticRegression documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html), [SVM practical guidance](https://scikit-learn.org/stable/modules/svm.html#tips-on-practical-use)

4. **Compare fixed BatchNorm during fine-tuning.** PyTorch BatchNorm updates running estimates in training mode and uses stored estimates during evaluation. Freezing parameter gradients alone does not freeze those buffers. After every `model.train()` call, put BatchNorm modules back in evaluation mode when this experiment is selected; leave `track_running_stats=True`. Keras' official transfer-learning guide also recommends preserving BatchNorm inference behavior when unfreezing a pretrained backbone. Whether that beats adapting statistics to candling must be determined using validation data. [PyTorch BatchNorm2d documentation](https://docs.pytorch.org/docs/stable/generated/torch.nn.modules.batchnorm.BatchNorm2d.html), [Keras transfer-learning guide](https://keras.io/guides/transfer_learning/)

5. **Inspect failure patterns before adding augmentation.** Compare wrong validation examples for missed egg boundaries, labels covering multiple objects, overexposure, low-resolution interiors, source artifacts, and near duplicates. The local [dataset research](dataset-research-2026-09-12.md) documents THESIS adaptive contrast equalization and Pat training augmentations. Additional aggressive brightness/color changes may destroy candling cues; treat augmentation choices as hypotheses and assess them on validation. Keep all crops from an original photo and all augmentation relatives in one group.

## Pinned DINOv2 loading and Windows notes

On September 12, `git ls-remote https://github.com/facebookresearch/dinov2.git HEAD` returned revision `7764ea0f912e53c92e82eb78a2a1631e92725fc8`. The pinned Hub entry points list `torch` as their required Hub dependency. The following is a source-verified loading pattern; its execution and GPU compatibility must still be checked by the training process. [Pinned Hub entry points](https://github.com/facebookresearch/dinov2/blob/7764ea0f912e53c92e82eb78a2a1631e92725fc8/hubconf.py), [PyTorch Hub API](https://docs.pytorch.org/docs/2.14/hub.html)

```python
import os
os.environ["XFORMERS_DISABLED"] = "1"  # Set before DINOv2 module imports.
import torch

backbone = torch.hub.load(
    "facebookresearch/dinov2:7764ea0f912e53c92e82eb78a2a1631e92725fc8",
    "dinov2_vits14",
    pretrained=True,
    trust_repo=True,
).eval()
```

The pinned attention implementation falls back to PyTorch scaled-dot-product attention when xFormers is missing or disabled; ordinary dense tensor batches use this path. Nested tensor attention with `attn_bias` requires xFormers. Therefore, an xFormers-disabled warning need not block frozen dense-batch extraction, and installing xFormers or changing the existing Torch/CUDA environment solely to remove that warning is unnecessary for this path. This is an inference from the source, not a claim of upstream Windows certification. [Pinned attention implementation](https://github.com/facebookresearch/dinov2/blob/7764ea0f912e53c92e82eb78a2a1631e92725fc8/dinov2/layers/attention.py)

The standard small-backbone weights resolve to [Meta's DINOv2 ViT-S/14 checkpoint](https://dl.fbaipublicfiles.com/dinov2/dinov2_vits14/dinov2_vits14_pretrain.pth). Record the downloaded file's SHA-256 independently: the code revision pins the loader, while the weight filename itself contains no content hash. [Pinned backbone loader](https://github.com/facebookresearch/dinov2/blob/7764ea0f912e53c92e82eb78a2a1631e92725fc8/dinov2/hub/backbones.py), [Pinned download base URL](https://github.com/facebookresearch/dinov2/blob/7764ea0f912e53c92e82eb78a2a1631e92725fc8/dinov2/hub/utils.py)

The coordinating experiment plan at the time of this note is frozen DINOv2 ViT-S/14, ConvNeXt-Tiny, and EfficientNet-B0, with logistic-regression `C = 0.01, 0.1, 1, 10` and one-versus-rest RBF SVM `C = 0.1, 1, 10`, each using no class weighting or balanced weighting. Selection is validation macro F1, then balanced accuracy, then accuracy. This is a declared experiment plan, not evidence those models trained or improved. If an SVM is converted to a portable Torch head, verify its decision scores and class predictions against the fitted estimator, including the binary-class case; decision margins are not probabilities.

## Evaluation discipline

Fit any scaler, feature selection, dimensionality reduction, classifier, or calibration parameters using development data only. Use pipelines to prevent preprocessing leakage. For a larger search, perform grouped cross-validation within the existing training partition, then use the existing validation partition for the declared final selection. Grouping by image family only approximates egg identity. Once the prior test results have motivated this improvement round, the same test is a retrospective comparison set, not a fresh prospective acceptance set. Report its complete before/after confusion matrices and error counts; obtain new independent eggs/batches for final confirmation. [Scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage), [Grouped cross-validation guidance](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data)

Avoid repeatedly opening test scores while choosing architectures or thresholds. Keep the search list, selection criterion, and selected checkpoint hash in the experiment record before test evaluation. Report balanced accuracy, macro F1, class support, per-class precision/recall, and full-set accuracy. An apparent gain of a few age examples is especially uncertain because only 35 test crops are available and the physical eggs are not identified.

## Confidence and review are separate from classifier accuracy

Temperature scaling fits a positive scalar on held-out logits to improve probability calibration. A positive temperature preserves the argmax ordering, so this method does **not** improve full-set top-1 accuracy by itself. Fit it without test labels; ideally use an independent calibration fold or cross-fitted development predictions when selection has already consumed the validation set. The age validation set is too small to treat calibrated percentages as dependable physical-device confidence. [Guo et al., On Calibration of Modern Neural Networks](https://proceedings.mlr.press/v70/guo17a/guo17a.pdf)

A review threshold can reduce mistakes among accepted predictions by abstaining on uncertain inputs, but this trades coverage for selective accuracy. Always report accepted count, review count, coverage, accuracy among accepted predictions, and class-specific accepted recall alongside full-set metrics. Zero accepted predictions has undefined selective accuracy; it is not 100% accuracy. A simple confidence cutoff does not automatically inherit the guarantees of a statistically bounded selective-classification method. Continue returning the existing `REVIEW_RECAPTURE` operational outcome until the project's actual release conditions are met. [Geifman and El-Yaniv, Selective Classification for Deep Neural Networks](https://papers.nips.cc/paper_files/paper/2017/hash/4a8423d5e91fda00bb7e46540e2b0cf1-Abstract.html)

## The unresolved obstacle to true duck age accuracy

The acquired age source still does not establish duck species, incubation timestamps, or physical egg/batch identities. This is explicit in the downloaded dataset's local [provenance audit](../data/public/thesis-egg-candling/audit-v1/audit.json), not a model limitation inferred from its accuracy. Even a high score on these labels would establish agreement with that source, not verified Day 16/18 duck accuracy.

The actionable data improvement is a controlled collection from the intended camera/candler: record `egg_id`, `batch_id`, confirmed species, incubation start and capture times, source of the age label, and a separately defined abnormal/reject reason with its verification. Hold out whole eggs and batches, including all their views, and test on a later capture session. Keep Day 16/18 labels from this collection distinct from unverified source labels. Do not merge THESIS age and Pat Reject into a single class task merely to fill the label set: source and class would be confounded, as already documented in the [dataset research](dataset-research-2026-09-12.md).
