# Day 16 / Day 18 / Unfertilized — 2026-10-19

The operator requested removal of R1, R2 and R3 from the next dataset, and clarified that the replacement class means **Unfertilized**, not uncertain or disabled filtering. The operator has no confirmed physical Unfertilized eggs for a live check and selected the existing explicitly annotated public dataset.

`data/local/retained-camera-unfertilized-20261019/manifest.jsonl` contains 3,719 images. Its SHA-256 is `01478d1619524c383539bf0d7bd3b730be5c5d82aa9f01a51db19e1018300885`. It preserves all 1,620 age-camera views: 30 initial photos, 90 earlier multiangle photos and 1,500 sweep photos. The 150 vendor-labelled R1/R2/R3 photos and all 1,888 historical Reject rows are excluded. Original evidence, datasets, trained releases and History are preserved as records of their original labels.

The 1,926 replacement images come only from literal **Unfertilized** COCO bounding-box annotations in the retained Pat v8 public audit. No Reject or Fertilized label is reinterpreted as Unfertilized or an exact age. Existing source-family and physical-egg partitions are preserved and checked for cross-partition byte/pixel duplicates.

| Partition | Day 16 | Day 18 | Unfertilized | Total |
|---|---:|---:|---:|---:|
| Training | 315 | 327 | 1,614 | 2,256 |
| Validation | 286 | 290 | 238 | 814 |
| Reserved test | 285 | 290 | 74 | 649 |

The retained DINOv2 ViT-S/14 + EfficientNet-B0 encoder is reused with a newly fitted three-class logistic head. Class weights balance effective training weight, and all views of one camera egg share its assigned weight. Three fixed camera weights (20/50/100) are compared using development validation only. The selected weight is 20. Validation embeddings use the actual ONNX CPU encoder; source PNG crops are encoded to JPEG at quality 95, and native camera JPEGs remain unchanged. Quality flags are evaluated on these exact serving inputs. Reserved test images are not used for fitting, threshold selection or inference.

The final run is `ml/runs/retained-unfertilized-serving-20261019`. Its selected validation counts are:

| Recorded class | Images | Raw correct | Correctly classified after gates | Recapture |
|---|---:|---:|---:|---:|
| Day 16 | 286 | 268 | 235 | 51 |
| Day 18 | 290 | 284 | 267 | 23 |
| Public Unfertilized | 238 | 238 | 159 | 79 |

These are development results from the data used for selection and gate calibration. The 661 accepted predictions match their recorded labels; coverage and correct-over-all are both 661/814 (81.20%). This is not an independent accuracy estimate. The camera views are correlated observations of ten validation age eggs. The public Unfertilized images have no independently verified embryo, egg or farm-batch records, and no Unfertilized physical-camera test was performed.

`unfertilized-trial-20261019` serves the new head for both attached images and three paused camera views. Its camera-head SHA-256 is `8c58f3f459c6be31521ba2cb59e2ef92c6409298c027b8f6a8c476539f817235`; its ONNX SHA-256 is `479211e3e587b0bce7d9bb1be1a318c48bdc62f632374f75d980ab1dbceda31e`. The registry SHA-256 is `d83a2fddd1d2bc46f910850cba7f56780e0bbfbcab33479e5a9e40801d64ab04`. It remains experimental, source-label-only and unauthorized for operational grading. Recapture, three-view consensus and motor stop/resume behavior remain enforced.

New model chunks are versioned under `deployment/model-parts/unfertilized-20261019`; the old chunks and releases remain byte-identical for rollback. `.vercelignore` excludes inactive release directories from the cloud package to stay below Vercel's size limit. To roll back, restore the previous release name in `deployment/active-release.txt`, remove that release directory from `.vercelignore`, add the now-inactive release directory to those exclusions, and redeploy. Web and Android support the new label while retaining historical Reject records. Android preview 0.4.2+6 is required to display Unfertilized results; it is not a production-signed or physically accepted app release.
