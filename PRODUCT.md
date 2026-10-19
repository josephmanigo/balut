# Product

<!-- impeccable:product-schema 1 -->

## Platform

web and native Android (Flutter)

## Stack

The approved greenfield stack is a monorepo with ESP-IDF C/C++ firmware, a Python FastAPI and SQLite laptop service, a React and TypeScript web dashboard, a Flutter Android application, Python ML tooling, and Supabase PostgreSQL, Auth, Storage, and Row Level Security definitions.

## Users

The primary user is a Balut vendor who manually loads one fertilized duck egg, starts a local inspection, reads a bilingual operational result, and removes or segregates the egg. Reviewers independently confirm or challenge machine results. Administrators manage devices, batches, model releases, evidence exports, and user access.

## Product Purpose

The product is a research prototype for repeatable, eight-view candling and appearance grading. It records verified incubation age separately from CNN morphology, preserves evidence, operates without internet, and routes uncertain or invalid inspections to review. Success means demonstrating the end-to-end AIoT workflow without converting prototype output into a food-safety claim.

## Positioning

The differentiating mechanism is a fail-closed 360-degree inspection: eight stopped views, explicit image-quality gates, immutable machine evidence, chronological-age versus appearance comparison, and a human disposition that never overwrites the machine result.

## Operating Context

One egg is placed in an enclosed long-axis holder. An ESP32-S3 controls capture, motion, illumination, safety inputs, local display, microSD queuing, and a compact int8 CNN. A Windows laptop hosts local records, the web dashboard, review, model management, and cloud synchronization. Flutter Android supports the nearby operator workflow. Remote clients may inspect and manage evidence but may not start physical motion or illumination.

## Capabilities and Constraints

### Current production web workspace

The production `/` entry offers **Create account** until this laptop has its single local account, then **Sign in** with the chosen username and password. Registration signs in immediately, preserves existing records, and stores a salted password hash in the database. The account survives service restarts; browser sessions do not. The workspace contains only **Analyze** and **History**. Analyze accepts one candling JPEG (up to 10 MB), displays the selected image, requests an appearance estimate, and saves the returned record. History presents the latest 50 records with optional metadata. Account access, analysis, and history expose loading and failure states instead of substituting sample results.

Analyze is **automatic only** in the production web workspace and Android 0.4.0; Attach photo was removed on 2026-10-17. The user confirmed an ESP32-CAM but no known presence sensor or lid switch. After connecting its JPEG snapshot address and confirming an empty-box reference, the laptop detects a steady scene change, captures once, analyzes, and shares the saved result with both clients. The preview refreshes before calibration and while analysis is paused. The current USB camera provides approximately one new frame per second. Removing the egg returns the view to its empty reference and rearms capture. Camera state and pending captures persist across service restarts. This scene-change heuristic is not a validated egg detector; hands, moved cameras, and lighting changes can trigger it. No physical actuation is enabled.

An unclear image receives no class and asks for another view. Show one recapture tip first; additional tips and record details are optional disclosures. On mobile, a completed result moves into view. Main operator copy supports English and Filipino; some errors, labels, and titles remain English, so complete localization is not claimed. See `docs/BOX_CONNECTION_2026-10-16.md` for current setup and verification boundaries.

This UI is the local research upload workflow, not evidence that physical candling, biological age verification, food-safety assessment, or device acceptance occurred. Accepted class estimates remain unauthorized for operational use. The result's research label and the visible appearance-only footer preserve that boundary. The custom login does not itself establish a completed security audit.

`apps/web/src/main.tsx` mounts `SessionGate` and `Workspace` in production. `App.tsx` remains the development simulator. Its nine destinations, human-review queue, synthetic eight-view demonstrations, and device-management screens are historical/development context, not required production sections. The broader Users, Product Purpose, Positioning, and Operating Context sections describe the research system and intended hardware workflow, not completed physical deployment.

On the Vercel deployment, a signed-in operator can click **Connect USB camera** in Box setup and select the existing FTDI camera adapter through the browser's Web Serial picker. Chrome or Edge on the capture computer reads the camera's 921600-baud JPEG/CRC protocol and uploads bounded frames under the browser session. This path needs no copied connector, Python installation, or device profile. Each browser connection requires a new empty view. The computer must remain awake with the tab open and internet available. Other signed-in devices can view the shared camera and history. USB drivers and physical capture still require verification on the actual computer; no physical actuation is added.

### Research workflow and physical-system constraints

The current Windows upload workflow supersedes the earlier mandatory-review interaction: the user requested automatic prediction and explicitly chose automatic recapture with no class assigned when an image is unclear. It predicts Day 16 / Day 18 / suspected Reject or requests a replacement JPEG, with no human review queue. The historical eight-view simulator and physical acceptance requirements below remain separate. See `docs/AUTOMATIC_RECAPTURE_2026-09-12.md` for measured accuracy and coverage; zero-error autonomous grading has not been demonstrated.

- Operational outcomes are `DAY_16_LIKE`, `DAY_18_LIKE`, `REJECT_SUSPECT`, and `REVIEW_RECAPTURE`.
- True chronological age comes from a documented incubation timestamp; the CNN assesses visual consistency only.
- `REJECT_SUSPECT` means segregate and review. It never means confirmed rotten, unsafe, pathogen-positive, disposable, or unsellable.
- Missing or invalid prerequisites, low confidence, view disagreement, incomplete coverage, device faults, and age/appearance conflict fail closed to review.
- The v1 prototype handles one manually loaded egg and does not include a carousel, conveyor, automatic physical sorting, iOS release, regulatory certification, or unattended remote operation.
- English and Filipino operator copy are required.
- Public-source exploratory CNNs are available, but a physical device, validated operational model, identified 300-egg dataset, qualified reviewer decisions, and vendor usability results are not available and must never be simulated as completed evidence.

## Brand Commitments

The product name is EggGrade IoT. Its voice is precise, calm, bilingual, and operational. Green may not imply food safety. Synthetic or simulated data must be labeled visibly.

## Evidence on Hand

The approved implementation plan and prior architecture research define the desired system and safety boundary. The workspace contains the software prototype, downloaded public candling datasets, and exploratory model checkpoints with local evaluation records. See `docs/TRAINING_RESULTS_2026-09-12.md` and `docs/ACCURACY_RESULTS_2026-09-12.md`. The second experiment improves age-source and Pat-source accuracy and records a duck-status regression. Those records do not supply hardware logs, physical-device acceptance, vendor testimony, or production-readiness proof.

## Product Principles

- Fail closed rather than guess.
- Preserve chronology, morphology, machine output, and human disposition as distinct facts.
- Keep physical safety local and independent from cloud availability.
- Make every result traceable to views, versions, thresholds, and immutable audit events.
- Label simulations, proposals, and unverified gates honestly.

## Accessibility & Inclusion

The web and Android operator surfaces use English and Filipino, keyboard-accessible controls where applicable, non-color-only status communication, visible focus states, readable warning copy, and responsive layouts suitable for vendor counters and field laptops.

The current Flutter Android surface mirrors the web account, Analyze, and History workflow. Its former demo login and device/review navigation are replaced. It connects to the same server account and saved predictions, with a JPEG picker and explicit recapture states. Records and model inference remain on the server. The current loopback Windows service requires a USB development bridge for Android access; public HTTPS deployment remains separate work. Preview signing and emulator checks do not establish physical-phone or app-store readiness.
