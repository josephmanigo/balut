# ML research package

The implemented package provides provenance validation, leakage checks,
session-level selective-classification metrics, confidence intervals, release
manifest validation, a MobileNetV2-0.35 training entry point, and ONNX opset 18
export.

Public candling datasets and exploratory trained checkpoints are available;
see the [accuracy comparison](../docs/ACCURACY_RESULTS_2026-09-12.md) and
[original measured results](../docs/TRAINING_RESULTS_2026-09-12.md). There is **no
validated operational Balut model or identified physical-egg dataset**.
The strict physical-data training entry point fails closed
unless the physical dataset manifest is valid, image files exist, train and
validation partitions exist, and a prospective-test partition has been
designated. The prospective partition is not loaded by `train.py`.

The [2026-10-04 comparison](../docs/HARDENING_AND_ACCURACY_2026-10-04.md) retains an 80-candidate frozen-feature experiment at `ml/runs/selective-v3-20261004`. Validation improves slightly, but historical accepted accuracy/coverage do not improve, so the served model is retained. The physical-manifest audit now checks image hashes, decoded-image identity, inspection identity, and augmentation parents. Session metrics report end-to-end recall and per-class abstention alongside accepted accuracy; confidence intervals assume independent trials.

Public dataset research and an exploratory source-label training workflow are
documented in [PUBLIC_TRAINING.md](PUBLIC_TRAINING.md). This optional workflow
does not create physical egg identities, verified age labels, or model releases.

The second experiment fits regularized classifiers to frozen DINOv2,
ConvNeXt, and EfficientNet representations, selects on validation only, and
retains the original historical test partitions. The new age and Pat models
improve source-label accuracy; duck status regresses. Use `-Version accuracy-v2`
with `scripts/Predict-Candling.ps1` to select a candidate explicitly. Its
verified ONNX inference path requires no Torch Hub download.

Audit a manifest:

```powershell
python -m balut_ml.cli audit-manifest data\manifest.jsonl
```

Training dependencies are listed separately from the API dependencies. The
dedicated `.venv-ml` environment has verified CUDA support on the RTX 3080;
see [public training instructions](PUBLIC_TRAINING.md) for its commands and lock file:

```powershell
python -m venv .venv-ml
.venv-ml\Scripts\python -m pip install -r ml\requirements-training.txt
```

Do not report frame-level validation loss as capstone accuracy. The release
gate requires egg-session metrics, frozen aggregation thresholds, int8 parity,
physical ESP32 known-answer results, and the untouched prospective test.
