# Public candling dataset research — 2026-09-12

The most useful current sources are **THESIS Egg Candling v6 for source-labelled Day 16/Day 18**, **Pat Balut Eggs Project v8 for its literal `Reject` annotations**, and **Team DevIn Duck Egg Candling for duck fertility/abnormality pretraining**. These are exploratory inputs: the public descriptions do not supply the physical egg IDs, verified incubation records, batch identities, or outcome confirmation required by this project's strict physical-data training route. Preserve original source labels and keep these experiments separate from validated capture manifests.

This note records live metadata and browser inspection. It does **not** claim that the archives were downloaded or a model trained; download audit and training artifacts must provide that evidence separately. All counts below are images, not independent physical eggs.

**Acquisition/training update:** The main task subsequently downloaded Team
DevIn v2, THESIS v6, and Pat v8 after user sign-in and terms acceptance. Actual
archive hashes, annotations, model checkpoints, and measured results are
recorded in [TRAINING_RESULTS_2026-09-12.md](TRAINING_RESULTS_2026-09-12.md).

## Sources to acquire

| Source | Current coverage and licence | Preferred acquisition / limits |
| --- | --- | --- |
| [THESIS — Egg Candling](https://universe.roboflow.com/thesis-mwxui/egg-candling-bdezy) | 1,561 project images; 19 object-detection classes: `Fertile-Day-1` through `Fertile-Day-18`, plus `Infertile`; CC BY 4.0. Live browser checked September 12. | Prefer [version 6](https://universe.roboflow.com/thesis-mwxui/egg-candling-bdezy/dataset/6): 1,425 images, **no augmentation**, train/validation/test 1,138/227/60. Auto-orient, fit within 640×640, adaptive contrast equalization. Species and day verification are undocumented. Preserve `Fertile-Day-16` / `Fertile-Day-18` as community source labels. |
| [Pat — Balut Eggs Project](https://universe.roboflow.com/pat-bteu2/balut-eggs-project-unfertilized-fertilized-and-reject-tgibj) | 648 project images; object-detection labels `Fertilized`, `Reject`, `Unfertilized`; CC BY 4.0. Preview alt text calls them Duck-Eggs. | [Version 8](https://universe.roboflow.com/pat-bteu2/balut-eggs-project-unfertilized-fertilized-and-reject-tgibj/dataset/8) has 1,556 images, split 1,362/130/64, 640×640 stretching and three outputs per training example. Keep only literal `Reject` boxes if creating the requested reject pool. Some images contain **both Reject and Unfertilized objects**, so whole-image classification without cropping would mislabel content. Description and reject-ground-truth procedure are absent. |
| [Team DevIn / ryleanthony-gabotero — Duck Egg Candling](https://universe.roboflow.com/ryleanthony-gabotero/duck-egg-candling) | 581 project images; image classification with `abnormal`, `fertile`, `infertile`; CC BY 4.0. The live owner description explicitly identifies it as a duck fertility classification dataset by Team DevIn. | Two published versions. Best species-relevant auxiliary classification candidate. Incubation days, independent eggs, capture protocol, and abnormality/outcome definitions are not documented on the page. `abnormal` is not silently equivalent to Pat `Reject` or validated `REJECT_SUSPECT`. |
| [MEGG — egg](https://universe.roboflow.com/megg/egg-wbglp) | 11,230 project images; `chicken_fertile`, `chicken_infertile`, `duck_fertile`, `duck_infertile`; CC BY 4.0. | [Version 1](https://universe.roboflow.com/megg/egg-wbglp/dataset/1) has 26,952 generated images; split 23,583/2,246/1,123; 224×224 stretching and three outputs per training example. Filter duck classes for duck fertility pretraining. No age or reject labels; description absent. |

For THESIS v6 and Pat v8, the version pages expose standard COCO JSON and YOLO download options. COCO is useful for extracting the exact labelled egg boxes into classification crops while retaining source image and annotation IDs. The actual downloaded archive's annotation categories and class counts must be checked before choosing the experiment.

## Additional exact-day and duck candidates

- [THESIS — Egg Embryonic Growth](https://universe.roboflow.com/thesis-mwxui/egg-embryonic-growth-dymzu) lists 1,078 project images with instance-segmentation labels `Fer-Day-1` through `Fer-Day-18`, and `Inf`. Its version-1 model page reports 1,550 images. CC BY 4.0; description absent. It is another explicit-day source, with **species unknown**, not confirmed duck data. Check overlap with the THESIS object-detection project before combining them.
- [Egg Incubator — day tracker for rcnn](https://universe.roboflow.com/egg-incubator-jxh2r/day-tracker-for-rcnn) currently lists **2,141 project images and six versions**, superseding the older search-card count of 820. Classes are `day04`–`day18`, `infertile`, `bad_candling`, and `0`; CC BY 4.0. Species and label provenance are undocumented. `bad_candling` describes a separate image-quality concept and must not become a biological reject. Version-specific category coverage still needs archive verification.
- [pj — EGG DUCK](https://universe.roboflow.com/pj-ovbgc/egg-duck-f4npv) lists 105 project images and `egg-crack`, `egg-dead`, `egg-fertile`, `egg-Infertile`; CC BY 4.0. Description absent. Its Roboflow Instant model panel says zero images for the model version, so the project-image count alone does not prove a usable export. Too small and poorly documented for validation.
- [DevIn Duck Egg Candling v2.0](https://universe.roboflow.com/ryleanthony-gabotero/devin-duck-egg-candling-v2-0-5c295) is a **different** object-detection project: 331 project images, `abnormal`, `fertile`, `infertile`, plus `DevIn-Duck-Egg-Candling-v2-0`; licence **BY-NC-SA 4.0**. Do not confuse its licence or counts with the 581-image CC BY 4.0 classification project.

## Bicol availability changed

[Bicol University — Balut Egg](https://universe.roboflow.com/bicol-university-orlm9/balut-egg) was opened twice in the browser, including by following its actual recommendation card on Pat's page. Both loaded **Project Not Found** and explained that the project may not exist, may have been deleted, or may not be shared with the viewer. Pat's recommendation card still shows 3,389 images, but this is not evidence of a currently accessible export. Earlier apparent 0–18 labels must be treated as historical, unverified metadata. A newly authenticated session may have different access, but that was not established by this research pass.

## Download access and public fallback search

Unauthenticated official Roboflow REST access to the THESIS version returned an API-key-required response. The main task's browser also found that Duck Egg Candling export requires sign-in. No authentication restriction was bypassed. Browser retrieval succeeded for the source and version details where plain HTTP or web extraction hit Cloudflare/fetch errors.

Public Kaggle API searches for `candling`, `egg fertility`, `duck egg`, and `balut`, and focused GitHub/Hugging Face searches did not identify a clearly licensed, immediately downloadable replacement covering duck Day 16/Day 18/Reject. Specific limitations:

- [Kaggle — Dataset Duck Egg](https://www.kaggle.com/datasets/rizkiramdhanhilal/dataset-duck-egg): its [public metadata](https://www.kaggle.com/api/v1/datasets/view/rizkiramdhanhilal/dataset-duck-egg) has a blank description and the licence field “Database: Open Database, Contents: © Original Authors”. No verified candling/day/label basis was established; do not substitute it merely because its title contains duck.
- [Kaggle — egg fertility 1275](https://www.kaggle.com/datasets/mostefatabbakh/egg-fertility-1275): public search metadata lists licence `Unknown`; not selected for training.
- [Kaggle — Chicken Egg Fertility](https://www.kaggle.com/datasets/ejfloresdmmmsu/chicken-egg-fertility): [owner metadata](https://www.kaggle.com/api/v1/datasets/view/ejfloresdmmmsu/chicken-egg-fertility) explicitly describes Philippine native **chicken** eggs at Days **7 and 10**, with background removal and uniform sizing; CC BY-NC-SA 4.0. This is a documented fertility fallback, but it does not answer the duck/day request and was not promoted to the requested dataset.
- [GitHub — duck_egg_fertility_detection](https://github.com/yumikopubangelo/duck_egg_fertility_detection): code is MIT-licensed, but the inspected repository tree contained evaluation figures and a few debug masks/overlays rather than an available raw training corpus. A software licence is not proof that absent source images can be acquired.

## Training interpretation

Train a public-data baseline only after recording the exact archive/version, its licence, class counts, SHA-256 hashes, and sample inspection. Keep source filename families and duplicate/near-duplicate clusters in one partition, including related augmented images. Physical egg identities remain unknown unless supplied by the source.

If combining THESIS Day 16/18 crops with Pat Reject crops, label and source will be partly confounded: a network may learn different cameras, contrast processing, or backgrounds. Report such scores as exploratory source-label performance, **not verified duck age accuracy or physical reject performance**. Prefer separate auxiliary age and duck-status models when that avoids presenting a single unsupported biological classifier. Neither `Infertile` nor `abnormal` supplies a verified meaning for the project's operational suspect/reject decision.

The strict project dataset and physical acceptance gates should remain unchanged. Public baseline training can proceed without inventing missing egg IDs, incubation timestamps, species, or outcome ground truth.
