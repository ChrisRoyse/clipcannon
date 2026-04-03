# Verification Report

## FSV Results

All FSV scripts passing. See [11_test_suite.md](11_test_suite.md) for full script list.

| Domain | Script | Checks | Result |
|---|---|---|---|
| Core Infrastructure | `fsv_core_infrastructure.py` | 154 | 154/154 |
| Pipeline + Tools | `fsv_pipeline_tools.py` | 189 | 189/189 |
| Billing + Dashboard | `fsv_billing_dashboard.py` | 84 | 84/84 |
| Server + Integration | `fsv_server_integration.py` | 323 | 323/323 |
| **FSV Total** | **4 primary scripts** | **750** | **All passing** |

Extended scripts (`manual_fsv_full.py`, `manual_fsv_iterative.py`, `manual_fsv_phase3.py`, `fsv_part1_pipeline.py`, `fsv_parts_3_to_7.py`, `manual_verify.py`) provide additional coverage across all domains.

## Pytest Results

681 tests across 44 files (480 ClipCannon + 201 voice agent). See [11_test_suite.md](11_test_suite.md) for breakdown.

## Lint

Ruff: Python 3.12, line length 100, rules E/F/W/I/N/UP/ANN/B/SIM/TCH. Source root `src/`.

## Codebase Metrics

| Metric | Count |
|---|---|
| Source packages | `src/clipcannon/`, `src/license_server/`, `src/voiceagent/` |
| Pipeline stages | 23 |
| MCP tools | 54 |
| Database tables (ClipCannon) | 23 core + 1 narrative + 1 prosody + 1 mouth_frames (vestigial) + 4 vector + 6 editing/rendering + 1 voice = 37 |
| Database tables (Voice Agent) | 3 (conversations, turns, metrics) |
| Encoding profiles | 7 |
| Target platforms | 7 |
| Pytest files | 44 (25 ClipCannon + 19 voice agent) |
| FSV scripts | 10 |
| Schema version (ClipCannon) | 4 |
