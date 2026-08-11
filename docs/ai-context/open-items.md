# Open items

## Current objective

The source-backed evaluation objective is resolved by rejection. Grid v1.0 and
Pullback v1.1 must remain disabled; neither may advance to shadow or demo.
There is no required live-testing follow-up for these versions because they
failed the development gate.

## Optional future research

1. If strategy work continues, write and preregister a distinct v1.2
   hypothesis, parameters, development gates, and stop conditions before
   running it.
2. Preserve the unopened validation (`2023-11-30` through `2025-03-24`) and
   test (`2025-03-25` through `2026-07-15`) partitions. Do not use them to tune
   rejected v1.0 or v1.1.
3. Consider profiling the calendar import/coverage path. It is correct and
   reproducible but currently slow on the full multi-year dataset.
4. Refresh the read-only FBS broker-property snapshot only if a future,
   separately preregistered strategy passes historical gates and becomes
   eligible for shadow parity.

## Safety invariants

- Keep all application order paths disabled.
- Do not create a locked Grid v1.0 or Pullback v1.1 config.
- Do not reinterpret the older news-bypass run as promotion evidence.
- Require explicit review after at least ten no-trade shadow sessions before
  any future 0.25% demo authorization.
- Revert to read-only on any configuration, data, broker, or parity drift.
