# Public dataset experiments

Status on 2026-09-12: three public archives acquired after user sign-in and
terms acceptance; exploratory source-label models trained locally. See
[measured results](../docs/TRAINING_RESULTS_2026-09-12.md) and
[the source research](../docs/dataset-research-2026-09-12.md).

The subsequent [accuracy comparison](../docs/ACCURACY_RESULTS_2026-09-12.md)
records frozen-feature candidates: age 62.9% to 82.9%, Pat status 94.1% to
96.5%, and duck status 95.4% to 93.1% on the same historical test partitions.
The duck regression is retained in the report; no later candidate was chosen
using those test results.

The optional public-source workflow preserves the publisher's original labels.
Its checkpoints do not authorize operational outcomes or bypass the physical
dataset audit in `balut_ml.train`. Image-level results cannot establish
Day 16/18 duck performance without verified species, timestamps, egg/batch
identities, and representative held-out captures.

## Installed local environment

Use `.venv-ml` for GPU training; `.venv` remains the local API environment.
Verified locally: Python 3.12.14, PyTorch 2.11.0+cu128, Torchvision 0.26.0+cu128,
CUDA available on NVIDIA GeForce RTX 3080 (10 GB). A CUDA forward/backward
calculation passed. Exact installed packages are saved in
`requirements-public-training.lock.txt`; install its CUDA packages with the
same official wheel index shown below. These checks establish environment
readiness. Completed training is evidenced separately by each run's checkpoint,
history, metrics, and test predictions.

```powershell
.\.venv\Scripts\python.exe -m venv .venv-ml
.\.venv-ml\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
.\.venv-ml\Scripts\python.exe -m pip install -r ml\requirements-public-training.txt
$env:PYTHONPATH = 'ml'
```

## Download and audit

The first usable duck-source candidate is
[Duck Egg Candling version 2](https://universe.roboflow.com/ryleanthony-gabotero/duck-egg-candling/dataset/2).
After signing in, download its classification-folder or classification-CSV
export. Preserve the original archive and its license/README files under
`data/public/duck-egg-candling/`. Never execute downloaded dataset code.

The importer supports class directories and Roboflow `_classes.csv` files.
It excludes ambiguous multi-label frames, unreadable images, exact duplicates,
and identical images with conflicting labels. It groups shared original
filenames and near-identical image content. Current near-duplicate grouping
requires dHash distance <=3 plus 32x32 RGB mean absolute difference <=6/255.
Grayscale hashes alone can collide for different egg silhouettes.

For augmented Roboflow exports, use `--preserve-source-splits`: test groups take
precedence over validation and training groups; remove related images from
the lower-priority splits. Published training augmentations never enter a
holdout. For unaugmented exports, the default rebuilds approximately 60/20/20
grouped folds. These are image groups; physical-egg isolation remains unproven.

```powershell
$env:PYTHONPATH = 'ml'
.\.venv-ml\Scripts\python.exe -m balut_ml.public_data data\public\duck-egg-candling\export --provenance ml\sources\duck-egg-candling.json --output data\public\duck-egg-candling\audit-new --preserve-source-splits
```

Inspect `audit.json`, `excluded.jsonl`, and `contact-sheet.jpg` before training.
The script stops if fewer than two classes have enough image groups for a
meaningful split. Do not fabricate groups or remove the gate to make training run.
Object detection sources such as THESIS/Pat use `balut_ml.crop_public_coco` for
source-attributed bounding-box crops; raw COCO exports cannot be passed as
classification folders. Crop provenance records original image hashes, box
coordinates, annotation IDs, and source labels. All crops from a source photo
share a group, including Roboflow filename variants.

## Train and inspect predictions

```powershell
.\.venv-ml\Scripts\python.exe -m balut_ml.train_public data\public\duck-egg-candling\audit-v2\manifest.jsonl --output ml\runs\duck-candling-new --epochs 25
.\scripts\Predict-Candling.ps1 -ImagePath path\to\candling.jpg -Model duck-status
```

MobileNetV3-Small starts from official Torchvision ImageNet weights. The first
three epochs adapt the head; later epochs fine-tune the backbone. The checkpoint
is selected using validation loss. The test set is evaluated only after training
and checkpoint selection. Saved outputs include source provenance, environment,
manifest and checkpoint checksums, epoch history, confusion matrix, per-class
precision/recall/F1, and individual test predictions.

Exact existing run inputs are `duck-egg-candling/audit-v2`,
`thesis-egg-candling/audit-v1`, and `pat-balut/audit-v2` under `data/public`.
Reuse their saved manifests for exact split reproduction. The first two audits
used the earlier conservative filename/dHash rule; Pat uses the refined RGB
check. Regenerating an audit with the current importer may change the split.

The age run uses 25 maximum epochs with early stopping; Pat uses 25 maximum
epochs and batch size 64. The duck and age runs use batch size 32. All use
seed 42 and validation-only checkpoint selection. Use fresh run directories.
Export a checkpoint using `python -m balut_ml.export_public path/to/best.pt`;
this checks float32 ONNX parity on the already-held-out source test images.

## Frozen-feature comparison

The `accuracy-v2` experiment compares 42 candidates per task using the exact
existing manifests. It fits regularized logistic/RBF classifiers using only
training examples and selects by validation macro F1, balanced accuracy, then
accuracy. All task selections are written before test feature extraction.
Frozen development feature caches, candidate metrics, pretrained hashes,
selection records, test scores, and exports are retained in `ml/runs/accuracy-v2`.
The fixed view policy is the average of original/flip embeddings, then L2
normalization. Decisions remain in the original source class space.

```powershell
$env:PYTHONPATH = 'ml'
.\.venv-ml\Scripts\python.exe -m balut_ml.benchmark_public --output ml\runs\new-comparison
.\.venv-ml\Scripts\python.exe -m balut_ml.export_features ml\runs\accuracy-v2\source-age16-18\best.pt
.\scripts\Predict-Candling.ps1 -ImagePath path\to\egg-crop.jpg -Model age16-18 -Version accuracy-v2
```

The benchmark requires a fresh output directory. Repeated experiments on
these historical test sets do not create fresh acceptance evidence. New
data must be collected and held out by physical egg/batch for that purpose.
The ONNX candidate exports include the flip ensemble internally and accept
only RGB 224x224 tensors after ImageNet normalization. Exported SVM decision
scores must not be labelled probabilities. DINOv2's source revision and all
three downloaded pretrained weight hashes are recorded with the experiment.
`-Version baseline`, the default, continues to use the original checkpoints.

The inference command always identifies the result as exploratory and returns
`REVIEW_RECAPTURE` for the operational outcome. Its source-class scores are
uncalibrated and must not drive automatic egg segregation.

Do not mix age classes from THESIS and Reject from Pat and then interpret a high
random-split score as biological learning: source camera/preprocessing may
identify the class. Evaluate separate source tasks first, then collect real
duck data from the target candling device for the intended combined model.
