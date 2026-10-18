# Empty-view recovery — 2026-10-18

The reported `checking_empty` state was reproduced with ten images captured after the user removed the egg. None matched the saved reference. Earlier cloud and direct USB images still contained an egg; these were kept separate from the confirmed empty captures.

Two calibration problems made recovery unreliable:

- The cloud reference action could immediately use three cached frames from before the operator's empty confirmation. It now discards cached frames and waits for three fresh, steady uploads.
- Calibration used a stricter whole-image motion check than empty recognition. Background lighting changes rejected a stable holder; measured holder correlations exceeded 0.98. Local and cloud calibration now use the existing exposure-aware empty-view comparison. Presence thresholds are unchanged.

The web interface now says `Waiting for an empty view` and explains that the saved reference has not matched. During this state or missing calibration, a collapsed recovery control lets the operator explicitly confirm an empty box and update the reference. Normal placement and removal remain automatic. Android source uses the same revised waiting message.

Validation: the cached-frame and background-change regression tests failed before their fixes, then passed. All 45 focused backend tests and 44 web tests passed. TypeScript/Vite production build and Flutter analysis passed. Existing tests retain obstructed-holder rejection, two-frame rearming, reconnect checks, pending-result recovery, and duplicate protection.

Live observations and replay reports are stored under `output/empty-box-20261018`; original camera snapshots and calibration backups remain under `deployment/private`. A calibration timeout was preserved separately. The detection remains image comparison, not a validated egg-presence sensor or evidence of biological age accuracy. No model, motor, firmware, or account change is part of this fix. No Android APK was rebuilt for the copy-only source change.
