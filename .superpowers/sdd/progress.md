# SDD ledger — plan: docs/superpowers/plans/2026-11-08-tap-simulator-reborn-trackstats.md

## Pre-flight interface scan
- Task 1 produces `models.py` (TelemetryPayload, PetItem, AccountInfo, SessionSummary), `config.py` (Settings).
- Task 2 consumes `models.py` for SQLite database operations. Checked: interfaces match.
- Task 3 consumes `models.py` (TelemetryPayload) for RateEngine. Checked: interfaces match.
- Task 4 produces `roblox_poller.py` (RobloxPoller) with async methods. Checked: interfaces match.
- Task 5 consumes Task 2 (Database), Task 3 (RateEngine), Task 4 (RobloxPoller), Task 1 (TelemetryPayload) for SessionManager. Checked: interfaces match.
- Task 6 consumes Task 5 (SessionManager), Task 2 (Database), Task 1 (models) for FastAPI routes & SSE. Checked: interfaces match.
- Task 7 produces CLI feeder script consuming Task 1 (TelemetryPayload schema) and target API contract. Checked: interfaces match.
- Task 8 consumes REST API endpoints & SSE stream from Task 6. Checked: interfaces match.
- Task 9 runs end-to-end integration across all modules.

Pre-flight: All interfaces aligned.

Task 1: complete (commits 71b693c..ea3c434, tests: pytest tests/test_models.py -> 3 passed)
Task 2: complete (commits ea3c434..13dc424, tests: pytest tests/test_database.py -> 3 passed)
Task 3: complete (commits 13dc424..e4750a0, tests: pytest tests/test_rate_engine.py -> 3 passed)
Task 4: complete (commits e4750a0..871554e, tests: pytest tests/test_roblox_poller.py -> 6 passed)
Task 5: complete (commits 871554e..ba3dbca, tests: pytest tests/test_session_manager.py -> 3 passed)
Task 6: complete (commits ba3dbca..9c0ef4a, tests: pytest tests/test_api_endpoints.py -> 3 passed)
Task 7: complete (commits 9c0ef4a..10a70f3, tests: pytest tests/test_feeder.py -> 2 passed)
Task 8: complete (commits 10a70f3..0dbefe1, tests: pytest tests/test_static_ui.py -> 1 passed)
Task 9: complete (commits 0dbefe1..93872fe, tests: pytest tests/ -> 25 passed)

Final: fixed Critical 1 (Rebirth session taps collapsed to 0) — test_rebirth_preserves_session_taps_gained RED->GREEN, suite 28/28
Final: fixed Critical 2 (Test suite isolation & idempotency) — isolated_test_db RED->GREEN, suite 28/28
Final: fixed Important 3 (Dangling session recovery reads snapshots) — test_dangling_session_recovery_reads_snapshots RED->GREEN, suite 28/28
Final: fixed Important 4 (Account deletion memory leak & FK integrity) — test_account_deletion_cleans_session_manager_memory RED->GREEN, suite 28/28
Final: fixed Important 5 (Rate engine session isolation & AFK distortion) — reset_account on session end RED->GREEN, suite 28/28
Final: fixed Minor 6 (Out-of-order jitter monotonic timestamp guard) — rec_ts clamp RED->GREEN, suite 28/28
Final: minor (deferred): Roblox presence status background loop enrichment
Final: minor (deferred): Synchronous SQLite calls in async FastAPI endpoints
