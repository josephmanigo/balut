# Single-image capture and physical age audit — 2026-10-18

The operator requested one analyzed image per placement. Automatic capture now stores one JPEG as a durable pending event and passes bytes to the existing single-image inference path. Preview frames still support presence checking and live display. The application does not collect timed angles or change the spinner.

Incomplete legacy multi-view collections are discarded with an empty recheck. Completed pending legacy scans retain their original images and idempotency key for recovery. History and model files remain intact.

The existing model failed the physical distinction in this diagnostic:

| User-reported egg | Images examined | Raw top score | Accepted output |
| --- | --- | --- | --- |
| Day 16 | Three saved camera images | Day 18 in all three | Unclassified |
| Day 18 | One fresh USB image | Day 16 | Unclassified |

All four images were below their winning class's training-similarity limit. Two Day 16 images and the Day 18 image also failed the margin check. A fixed crop around the holder did not correct either age. This is evidence of failure on these two eggs; it is not an accuracy estimate for a population. Removing the unfamiliarity gate would permit wrong age labels in this sample.

The user reports five different uncooked eggs per age from a balut farm, with ages confirmed from incubation dates. Exact incubation timestamps and farm batch records have not yet been captured. Images and diagnostic results are under `output/single-capture-20261018`. These are user-reported labels, not a prospective validated dataset.

Software verification: 54 backend tests across capture, cloud state, and legacy multi-view recovery; 44 web tests; TypeScript/Vite production build; Flutter analysis. These checks establish software behavior, not physical age accuracy. Android source copy was updated; no APK was rebuilt.
