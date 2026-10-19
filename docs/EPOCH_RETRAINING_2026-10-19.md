# Epoch retraining and Reject display name — 2026-10-19

Actual image fine-tuning completed **11 epochs**, with **epoch 6** selected using validation data. The candidate improved raw historical accuracy slightly, but increased wrong accepted Day 18 classifications. It failed the predefined regression checks and **was not promoted**. The active release remains `unfertilized-trial-20261019`.

The web and Android apps now display **Day 16 / Day 18 / Reject**. Reject is the operator-requested display name for the existing Unfertilized source category. Historical/API `UNFERTILIZED` values remain readable and are not rewritten. This change does not establish a general defect category or confirm embryo absence.

## Dataset and source labels

The local manifest is `data/local/retained-camera-epochs-reject-20261019/manifest.jsonl`. It preserves all 3,719 original images and partitions: 2,256 training, 814 validation, and 649 historical test images. It includes the 30 initial age images, 90 three-angle views, and 1,500 additional age views. The 150 vendor Reject photos from R1/R2/R3 remain excluded, as previously requested.

Original `source_label` values are preserved. A separate `training_label` maps the public source's explicit `UNFERTILIZED` annotations to the requested `REJECT` output name. No vendor Reject egg was relabelled as Unfertilized. Public annotations are not independently verified biological ground truth.

All views of each physical egg remain in one partition. Training contains five identified physical eggs per age; validation contains five per age; the historical test contains five per age. The 540 repeated camera test views represent ten eggs, not 540 independent eggs. Source image families and hashes also retain their partitions.

## Actual image training

Run: `ml/runs/finetuned-epochs-reject-20261019`.

- Retained DINOv2 ViT-S/14 + EfficientNet-B0 encoder; current deployed classifier initializes the head.
- Trainable: last two DINOv2 blocks, last two EfficientNet feature blocks, and classifier head; 4,684,851 trainable parameters.
- AdamW; encoder learning rate 0.00001, head learning rate 0.0005; batch size 16; seed 42.
- Maximum 15 epochs; patience 5. Completed 11; selected epoch 6. Selection uses validation source/camera group recall, camera age recall, macro F1, and validation loss.
- Training augmentation only: rotation ±8 degrees and brightness/contrast ±8%. Batch-normalization statistics stay frozen. Physical egg weights are shared over their views.
- Train curves record actual minibatch predictions during each epoch. Validation curves record completed checkpoints on fixed inputs. Loss is cross-entropy; precision, recall, and F1 are macro averages.
- The selected checkpoint was exported to ONNX and all 814 validation images recomputed on CPU. CPU PyTorch/ONNX maximum score difference was 0.00000662; all validation raw labels agreed with GPU results.

Selected validation raw accuracy was **800/814 (98.28%)**. After recapture gates, 690 images were classified correctly, zero incorrectly, and 124 requested recapture. These development results do not establish field accuracy.

Two earlier classifier-head-only experiments are retained locally. The gated-selection run completed 57 epochs and selected epoch 37. Its historical regression also failed. It is not active. No historical test images were used for gradient updates, and no thresholds were changed after evaluating either locked candidate.

## Historical comparison and deployment decision

The 649 images had already been inspected in earlier experiments. This is a historical regression comparison, not a new independent confirmation study. Every image was evaluated once through the actual ONNX CPU camera path, using its unchanged native JPEG or the same public PNG-to-JPEG conversion as validation.

| Measure | Active baseline | Fine-tuned candidate |
| --- | ---: | ---: |
| Raw accuracy | 550/649 (84.75%) | 553/649 (85.21%) |
| Accepted accuracy | 423/444 (95.27%) | 441/466 (94.64%) |
| Coverage | 444/649 (68.41%) | 466/649 (71.80%) |
| Correct / all inputs | 423/649 (65.18%) | 441/649 (67.95%) |
| Wrong accepted predictions | 21 | 25 |
| Wrong accepted Day 16 | 3 | 2 |
| Wrong accepted Day 18 | 18 | 23 |

The candidate passes raw-age accuracy, per-class correct counts, and coverage checks. It fails the requirement that accepted errors must not increase for either age. More classifications do not compensate for the increased Day 18 error count under this predefined rule. The active classifier and its recapture policy remain unchanged.

Candidate raw matrix (rows recorded; columns predicted Day 16, Day 18, Reject):

```text
252  33   0
 63 227   0
  0   0  74
```

Candidate gated matrix (last column is Recapture):

```text
182   2   0 101
 23 202   0  65
  0   0  57  17
```

No 99% claim is supported. A new study needs more distinct eggs and batches, with incubation dates and source/egg grouping fixed before training. Extra views of the same thirty eggs do not provide the same evidence as new eggs. No confirmed physical Unfertilized egg was available for a live check.

## Downloadable local results

- `output/model-results/EggGrade-IoT-Finetuned-Epoch-Results-20261019/results.png`: ten actual epoch plots and both historical confusion matrices in one PNG.
- `output/model-results/EggGrade-IoT-Finetuned-Epoch-Results-20261019/results.csv`: actual metric values for all eleven epochs.
- `output/model-results/EggGrade-IoT-Finetuned-Epoch-Results-20261019.zip`: graph, CSVs, configuration, locked metrics, comparison checks, and per-image outcomes. No raw private photos or credentials.
- `artifacts/EggGrade-IoT-Android-0.4.4-preview.apk`: updated Reject display name; uses the same server model as the website. Preview APK uses the debug signing key.

The experimental checkpoint and sealed candidate remain local for reproducibility. Existing models, original photos, prediction history, and camera pause/rotation behavior are preserved. Backend tests: 226 passed. Web: 48 tests, type check and production build passed. Android: analysis and 21 tests passed, release preview APK built. Physical phone installation and a new live egg cycle were not performed for this change.

## Technical defense wording

“We fine-tuned the retained image model for eleven epochs and selected epoch six using validation data. The training and validation plots show actual recorded loss and classification metrics. Validation accuracy reached 98.28%, but the historical test achieved 85.21% raw accuracy. Our recapture system classified 71.80% of test images, with 94.64% accuracy among those classifications. Because Day 18 accepted errors increased, we retained the previous model in the app. This shows why we evaluate errors and coverage rather than selecting a model from training accuracy alone. The Reject name represents the source dataset's Unfertilized category and is not a food-safety certification.”
