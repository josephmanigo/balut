# Public web performance improvements

Target: https://egggradeiot.vercel.app. Measurements and software checks were taken on 2026-10-19.

## Changes

- Keep History mounted after the first visit. Switching back displays the loaded records immediately. New saved results and Refresh still reload history.
- Remove the automatic workspace's model-catalog request and experimental-model messages. Result validation and stored release provenance remain unchanged.
- Request camera status without a preview while History is visible or a direct USB preview is available. Shared viewers still receive camera images. Keep USB capture mounted when switching destinations.
- Stop and cancel status polling when the browser tab is hidden or the component unmounts. Resume on visibility change. Wait for each response before polling again, back off failures, and poll cloud scan progress every 500 ms instead of 1500 ms.
- Select only camera fields needed for status from Supabase. Metadata polls do not fetch preview bytes, frame-comparison history, or upload-key history. Capture mutations still load and save the full state under the existing lease.
- Reuse HTTP connections for cloud reads and writes, with shutdown cleanup. This follows the [HTTPX client lifecycle](https://www.python-httpx.org/advanced/clients/). Query projection uses [PostgREST JSON field selection](https://docs.postgrest.org/en/stable/references/api/tables_views.html#json-columns).
- Enable gzip for larger responses. Cache built assets for one year under their content-hashed names. Keep HTML, account responses, history, and camera state private and uncached.
- Exclude legacy simulator CSS from the production build. Retain shared resets, theme tokens, focus styles, spinner, and reduced-motion behavior.
- Keep the optional local gateway and JavaScript proxy compatible with the preview query. Query and destination validation remain strict.

## Measurements

| Measurement | Before | After |
| --- | ---: | ---: |
| Production CSS, uncompressed | 39.21 KB | 20.87 KB |
| Production CSS, build-reported gzip | 8.63 KB | 4.99 KB |
| Model-catalog requests on automatic workspace mount | 1 | 0 |
| History requests across two visits without a new result | 2 | 1 |
| Connections used by three sequential cloud requests in a local HTTP test | 3 | 1 |
| Live cloud camera response bytes, full state versus metadata projection | 235,907 | 15,045 |
| Median live cloud camera read time, three paired samples | 511 ms | 202 ms |
| Cloud scan polling delay after a response | 1500 ms | 500 ms |

The live read comparison used a reused client for both query forms. Full-state samples were 1078, 511, and 433 ms; metadata samples were 211, 202, and 195 ms. The smaller response is approximately 94% fewer bytes. Camera state can change between reads. These are database-request measurements from this laptop, not end-to-end inspection times or a controlled production speed guarantee.

Before publication, the public site served `index-BE9LFWOX.js` and `index-Bb02ouBm.css`. Unauthenticated session checks returned 200 in 478 and 297 ms. Public hosting already compressed the HTML; the new middleware also covers local serving and larger API responses.

## Verification

- `npm run verify`: TypeScript, 55 web tests, and production build passed.
- The final full edge API suite passed: 232 tests. The JavaScript proxy suite passed: 7 tests. Checks cover query projection, connection reuse, cache policy, preview omission, sessions, capture recovery, and both gateway implementations.
- The metadata projection was executed against the live database with read-only requests. Both preview and metadata status conversion passed against the current row.
- Browser smoke checks used an isolated account and database: sign-in, Analyze, History, repeated tab switching, desktop and mobile layout, and no browser console errors. No production captures were created by these checks.
- No model weights, active release, schema, account credentials, camera calibration, or capture thresholds are changed by this patch.

Deployment completion must be verified separately from the local build. Physical camera refresh time and inference duration are outside the measurements above.
