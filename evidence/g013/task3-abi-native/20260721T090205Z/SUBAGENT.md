# Native subagent integration

- Subagents spawned: 1 (/root/lane2_plan_extract)
- Requested model: gpt-5.6-terra
- Native surface limitation: role/model routing was unavailable; prevalidated role intent was recorded in the worker subagent ledger.
- Serial searches before spawn: fewer than 3.
- Findings integrated:
  - Require exact ABI equality: armeabi-v7a, arm64-v8a, x86_64; reject x86, unexpected ABIs, and Sync.
  - Require every ELF PT_LOAD alignment to be at least 0x4000.
  - Require APK zipalign -P 16 and exact API 37 / 16 KiB runtime identity.
  - Require bidirectional official fixture compatibility and all AC-08 notification/thread/wrong-key/restart/migration semantics.
