# Compatibility Change Ledger

## Baseline

- **Upstream tag/commit:** `v10.19.0` / `0ab8d6961afb038d0e0c69478de45dda3958d641`
- **Realm Core gitlink:** `5533505d18fda93a7a971d58a191db5005583c92`
- **Status:** no production source changes are authorized or present at this baseline.

## Mandatory entry fields

Every later diff to a production `*.kt`, `*.java`, `*.c`, `*.cpp`, or `*.h` file must add one row with all of:

| failure-id | reproduced failing task/log | minimal change and rejected alternatives | affected file(s) | regression test/evidence | status |
| --- | --- | --- | --- | --- | --- |

Cosmetic refactors and dependency modernization without a reproduced blocking failure are rejected.
