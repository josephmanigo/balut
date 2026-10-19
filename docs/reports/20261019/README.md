# EggGrade IoT: defense guide and model decision

Start with [the easy defense PDF](EggGrade-IoT-Defense-Guide.pdf). Each panel question has a short spoken answer, supporting numbers, evidence references, and a limitation. Pages 4-6 explain the metrics and confusion matrices. Page 13 shows actual experimental epoch graphs.

**Decision: keep `unfertilized-trial-20261019` active.** The full-frame RBF candidate raised historical raw accuracy from 550/649 (84.75%) to 572/649 (88.14%), but reduced correct accepted results from 423/649 (65.18%) to 315/649 (48.54%). Its coverage also fell from 68.41% to 48.54%. It does not qualify for replacement.

The best selected development result was 96.87% overall, with physical Day 16 / Day 18 recall of 95.19% / 94.63%. These development results informed selection. They are not an independent 96% field result. No candidate meets the complete accuracy, per-class and coverage requirements.

The requested 1,590 photos are included: 90 three-view photos plus 1,500 rotation photos. They represent 30 eggs. All related views stay in the same egg partition. R1/R2/R3 are excluded. The public Unfertilized source class is displayed as Reject; it is separate from recapture.

## Files

- [Aggregate evidence](model-evidence.json): full metric precision, matrices, confidence intervals, actual epoch history, model identity, and source evidence hashes.
- [Raw confusion matrix](raw_confusion_matrix.png) and [matrix including recaptures](selective_confusion_matrix.png): current app model, 649 historical images.
- [Actual epoch curves](epoch-curves.png) and [epoch experiment matrix](epoch-confusion-matrix.png): inactive 64-unit MLP, explicitly separate from the app model.
- [Full reproducibility notes](../../scientific-reproducibility.txt) and [future field protocol](../../scientific-field-protocol.txt).

## Rebuild the guide

Run `python scripts/build_easy_defense.py` from the repository root with NumPy, Matplotlib, pypdf and ReportLab installed. Existing local report dependencies in `tmp/pdfdeps` are reused when available. The command uses the committed aggregate evidence and does not need private photos, credentials or model weights. It checks matrix totals, metric calculations, experiment counts and PDF pagination. Render every page and review layout after changing the report.

`--refresh-evidence` imports the locally verified scientific packet and measured run summaries; it requires the private local evidence paths. It does not train or deploy a model. The full technical packet retains the detailed ten-question answer sheet and full-precision repeat logs locally.

## Limits

Identical saved inputs passed strict zero-gap in the tested scope. Fresh physical zero-gap remains unmeasured. **ZERO-GAP REQUIREMENT NOT MET. FIELD ACCURACY NOT YET ESTABLISHED.** A new independent confirmation requires new referenced eggs, batches and actual camera testing. The historical test was already inspected. Public egg/batch identity and biological label verification remain incomplete.

Only aggregate results and graphs are published here. Camera photos, source datasets, account records, credentials, live history and inactive model weights remain local. The active release and three-view motion workflow are unchanged.
