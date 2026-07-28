# Grid v1.0 historical result

**Decision: REJECTED at the development gate (`development_rejected`).** The
default news source contains no explicit source-backed date confirmations, so
every candidate session was conservatively rejected as `news_blocked`. The
frozen candidate will not be locked and must not advance to the shadow/demo
plan.

## Frozen inputs

- Config: `config/grid-v1.0.json`
- Config SHA-256: `f7fc276470fbd8ffef8b33800b0d3b67541b411e24e1875c70b7669b06552d2d`
- Canonical data manifest: `artifacts/market/manifest.json`
- Data manifest SHA-256: `3dd947d99b3f5420051fc2c9ea9ff9142bf1416c52a387696319f63e46187c1e`

## Partition access and gate result

The pipeline accessed only the development partition, `2020-01-02` through
`2023-11-29`. It did not access validation (`2023-11-30` through
`2025-03-24`) or test (`2025-03-25` through `2026-07-15`), because neither
candidate session passed the development gate. No window was selected.

| NY session | Baskets | News-blocked sessions | Base expectancy R | Base PF | Base max DD R | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 08:45-09:45 | 0 | 1,213 | 0.000000 | N/A | 0.000000 | Failed |
| 09:30-10:30 | 0 | 1,213 | 0.000000 | N/A | 0.000000 | Failed |

All 2,426 rejection rows record `reason=news_blocked` and
`news_status=missing_confirmation`, with `data/news_blackouts.csv` recorded as
the audited source path. Both development gate booleans were `false`.

Because no session had positive news-clear evidence, this run makes no claim
about corrected contract-aware strategy expectancy. Historical cash P&L now
uses the plan-implied cash value per price unit, which is 100 for production
XAUUSD sizing and remains 1 for unit-scale synthetic fixtures.

## Safety and next decision

The research command was historical/read-only. **No demo order was attempted.**

Exact next decision: reject Grid v1.0; do not create
`config/grid-v1.0-locked.json`, and do not begin the shadow/demo plan. Before
any new frozen historical run, populate `data/news_blackouts.csv` with
source-backed rows explicitly confirming every candidate trading date and
covering any high-impact USD or gold blackout intervals.
