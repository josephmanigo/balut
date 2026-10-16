# Test automatic analysis

Open Chrome or Edge on this laptop at http://127.0.0.1:8765 and sign in as `operator` using the password copied by `scripts/Copy-Balut-Login.ps1`.

Open **Analyze egg**. Upload any of these JPEGs and press **Analyze egg**. There is no model dropdown.

| Image | Expected prediction |
|---|---|
| `day_16.jpg` | Day 16 |
| `day_18.jpg` | Day 18 |
| `reject.jpg` | Reject — suspected |

Each result should show **Image prediction · human confirmation required** and a saved record. These validation fixtures verify software behavior; they are not independent accuracy examples. Their original source labels, source hashes, and validation provenance are in `manifest.json`.

For the model's class-specific accuracy and limitations, read [the automatic-analysis report](../../docs/AUTOMATIC_EGG_ANALYSIS_2026-09-12.md).
