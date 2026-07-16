# Production Diff Ledger

This ledger fixes the G001 production boundary at upstream `v10.19.0` (`0ab8d6961afb038d0e0c69478de45dda3958d641`).

## Bootstrap entry

| id | change class | allowed paths | production source diff | validation |
| --- | --- | --- | --- | --- |
| G001-baseline | provenance only | `.gitignore`, `evidence/provenance/`, `tools/capture-baseline.py`, `tools/verify-baseline.sh`, `tools/verify-release-tag.sh`, `tools/test-verify-release-tag.sh`, these ledgers | none | `tools/verify-baseline.sh`; `tools/test-verify-release-tag.sh` |

Future production changes must reference a `failure-id` in `compatibility-change-ledger.md` before they are committed.
