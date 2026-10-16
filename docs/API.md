# Local API contract

Interactive OpenAPI is served at `http://127.0.0.1:8000/docs` while the edge
service runs.

## Authority headers

- Local operator mutations require `Authorization: Bearer <local token>`,
  `X-Balut-Origin: local`, and `Idempotency-Key`.
- Device ingestion requires `X-Device-Id`, `X-Device-Timestamp`,
  `X-Device-Signature`, and `Idempotency-Key`. The signature is HMAC-SHA256 of
  `timestamp.device_id.raw_body` with the registered development secret.
- Remote/cloud callers do not receive a scan-start route.

Development tokens in `.env.example` are for loopback testing only.

## Implemented endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Explicit simulator/hardware/model readiness |
| GET | `/api/v1/dashboard` | Counts, device readiness, outstanding gates |
| GET | `/api/v1/inspections` | Immutable inspection summaries |
| GET | `/api/v1/inspections/{id}` | Eight views, aggregate evidence, reviews, audit |
| POST | `/api/v1/inspections/{id}/reviews` | Append a human disposition |
| POST | `/api/v1/device/inspections` | HMAC-authenticated device manifest ingestion |
| POST | `/api/v1/scans` | Local start request; fails closed without hardware |
| POST | `/api/v1/simulator/run` | Development-only synthetic probability scenario |
| GET/POST | `/api/v1/batches` | Research batch registry |
| GET/POST | `/api/v1/eggs` | Physical-egg registry |
| GET | `/api/v1/audit` | Hash-chained audit events |
| GET | `/api/v1/sync/status` | Store-and-forward queue status |
| GET | `/api/v1/export/manifest` | Research export summary with simulated-record flag |

## Result interpretation

Machine fields are immutable. A later human disposition appears under
`reviews`; it never changes `outcome`, `canonicalHash`, or the stored per-view
probabilities. Synthetic records contain `isSimulated: true`, authority
`SHADOW_ONLY`, and model release `SIMULATOR_NO_CNN`.
