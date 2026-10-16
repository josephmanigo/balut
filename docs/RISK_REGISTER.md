# Prototype risk register

Severity and likelihood must be re-scored after physical bring-up. “Control in
source” is not proof that the physical control works.

| Hazard / failure | Potential effect | Current control | Verification / residual decision |
|---|---|---|---|
| Lid opens during rotation | Pinch, egg drop, spill | Dual-pole NC lid switch; hardware enable removal; latched firmware safe stop | 100/100 cutoff trials in every active state; measure cutoff, inspect guard |
| E-stop pressed | Continued motor/light energy | Latching NC hard-wired gate plus sensed pole | 100/100 trials; ESP32 unplugged gate-off test |
| GPIO active during boot/reset | Unexpected movement/heating | External inactive bias; non-energizing default firmware | Scope every boot, brownout, watchdog, cable disconnect |
| 12 V miswire | Board damage, heat, touch hazard | Fused branch architecture, keyed connectors, labels | Continuity/voltage checklist before connecting electronics |
| LED overtemperature | Egg/chamber heating, component damage | Constant-current driver, heatsink, pulse control, nearby temperature sensor | Consecutive-scan thermal profile and independent probe |
| Motor overtorque / clamp force | Egg crack or drop | Spring travel limit, compression stop, current limit, compliant cups | Force/current measurement across egg sizes; 100 loaded cycles |
| Incomplete/slipping rotation | Correlated or missing evidence | Home sensor, engineering fiducial trials, adjacent-image change gate | Full-revolution and size-stratified slippage tests |
| Saturated/dark/blurred image | Incorrect appearance grade | Locked optics and quality gates | Challenge set plus ten repeat scans per egg |
| Missing age timestamp | False chronological claim | Separate recorded-age field; abstention | API/dataset validation and operator protocol audit |
| Low confidence/view disagreement | Forced machine guess | `REVIEW_RECAPTURE` selective policy | Frozen threshold validation; coverage reported with accuracy |
| Reject class overinterpreted | Unsafe or misleading vendor action | “Reject—review” wording; no biological reason invention | Copy scan, usability interviews, reviewer protocol |
| Database/image partial failure | Result without complete evidence | Content-addressed durable JPEG stage plus atomic SQLite result transaction | Hash mismatch, disk-full, rollback, restart tests |
| Duplicate/replayed upload | Duplicate research records | Event UUIDs, HMAC freshness, idempotency keys, cloud upserts | Replay/out-of-order/recovery tests |
| Cloud or laptop unavailable | Scan blocked or load remains energized | Box-local result and microSD queue; safety local | Disconnect trials during each state |
| Credential leakage | Unauthorized records/commands | Service role excluded from clients; local origin and device HMAC | Artifact scan, rotation plan, RLS tests |
| Dataset leakage | Inflated accuracy | Physical egg and batch partition audit; train-only augmentation | Manifest audit and frozen prospective split |
| Reviewer bias | Inflated label agreement | Independent, initially blinded dispositions | Preserve both originals and adjudication audit |

Any physical safety control without a completed verification record remains
`BLOCKED`, regardless of its row in this register.
