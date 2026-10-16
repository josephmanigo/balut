# Plan-to-implementation traceability

| Plan requirement | Source location | Evidence level |
|---|---|---|
| Four fail-closed outcomes and flags | `contracts/domain.json`, `balut_api/domain.py` | Implemented/tested locally |
| Six-of-eight, confidence, margin, agreement, age conflict | `balut_api/aggregation.py`, `firmware/main/decision_policy.c` | Python tested; C source only |
| Atomic result/audit/outbox | `balut_api/database.py` | SQLite tests pass locally |
| Replayed event resistance | idempotency table and API tests | Local test evidence |
| Local-only scan authority | `balut_api/security.py`, `/api/v1/scans` | API test evidence |
| Eight-view inspection UI | `apps/web/src/App.tsx` | Built and browser review required |
| Flutter local/cloud authority | `apps/mobile/lib/api_client.dart` | Source only; Flutter unavailable |
| Hard-wired safety boundary | `docs/WIRING_PLAN.md`, firmware gate abstraction | Design/source only; physical gate blocked |
| ESP32 safety priority/state machine | `firmware/main` | Source only; ESP-IDF unavailable |
| Dataset leakage protection | `ml/balut_ml/dataset.py` | Unit tests pass locally |
| Session selective metrics | `ml/balut_ml/metrics.py` | Unit tests pass; no study data |
| Model release contract | `ml/balut_ml/release.py`, Supabase migration | Source only; no model release |
| Private remote evidence and RLS | `supabase/migrations` | Migration source; not provisioned/tested |
| Physical, research, usability gates | `docs/VALIDATION_LEDGER.md` | Explicitly blocked |
