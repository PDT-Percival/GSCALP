# Grid v1.0 historical result

**Decision: REJECTED at the development gate (`development_rejected`).** The
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

| NY session | Baskets | Base expectancy R | Base PF | Base max DD R | Stress expectancy R | Stress PF | Stress max DD R | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 08:45-09:45 | 1 | -0.000306 | 0.000000 | 0.000306 | -0.050532 | 0.000000 | 0.050532 | Failed |
| 09:30-10:30 | 5 | -0.005233 | 0.142185 | 0.026163 | -0.055448 | 0.000000 | 0.277239 | Failed |

The corresponding selection scores were `-0.050532` and `-0.058565`;
both development gate booleans were `false`.

## Safety and next decision

The research command was historical/read-only. **No demo order was attempted.**

Exact next decision: reject Grid v1.0; do not create
`config/grid-v1.0-locked.json`, and do not begin the shadow/demo plan. Any
future candidate must use a separately versioned configuration and a new
frozen historical run.
