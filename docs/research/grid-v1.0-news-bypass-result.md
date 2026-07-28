# Grid v1.0 news-bypass exploratory result

**Decision: REJECTED at the development gate (`development_rejected`).** This
run intentionally bypassed the historical news-confirmation requirement at the
user's request. It is not source-backed evidence that the sessions were safe to
trade, and it must not be used to unlock shadow or demo execution.

## Bypass input

The run used an ignored temporary CSV:

- `artifacts/news-bypass/grid-v1.0-user-approved-news-bypass.csv`

That file contains one broad `NO_HIGH_IMPACT_EVENTS` interval from
`2020-01-02T00:00:00+00:00` through `2026-07-16T00:00:00+00:00`, with source
`USER_APPROVED_NEWS_BYPASS_NOT_SOURCE_BACKED_SINGLE_INTERVAL`.

Coverage audit:

- Candidate session checks: 4,772
- Clear under bypass: 4,772
- Ready under bypass mechanics: `true`

## Frozen inputs

- Config: `config/grid-v1.0.json`
- Config SHA-256: `f7fc276470fbd8ffef8b33800b0d3b67541b411e24e1875c70b7669b06552d2d`
- Canonical data manifest: `artifacts/market/manifest.json`
- Data manifest SHA-256: `3dd947d99b3f5420051fc2c9ea9ff9142bf1416c52a387696319f63e46187c1e`
- Output directory: `artifacts/reports-news-bypass/`

## Result

The run accessed only the development partition. It did not access validation
or test, because neither candidate session passed the development gate.

| NY session | Baskets | Win rate | Base expectancy R | Base PF | Base max DD R | Stressed expectancy R | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 08:45-09:45 | 1 | 0.0% | -0.030645 | 0.000000 | 0.030645 | -0.103207 | Failed |
| 09:30-10:30 | 5 | 40.0% | -0.523270 | 0.142185 | 2.616350 | -0.594789 | Failed |

Aggregate development rejection reasons after removing the news gate:

| Reason | Count |
| --- | ---: |
| neutral_bias | 1,093 |
| invalidation_too_far | 749 |
| spread_too_wide | 455 |
| no_confirmed_pivot | 121 |
| invalidation_too_close | 1 |
| pending_expired | 1 |

Only six development baskets were produced across both windows, and both
windows had negative base and stressed expectancy. The sample is too small and
too weak to justify locking any session.

## Safety decision

Even without news filtering, grid v1.0 remains rejected. Do not create
`config/grid-v1.0-locked.json`, do not begin shadow mode, and do not enable demo
execution from this result.

The next strategy step is to design a separate v1.1 candidate instead of
loosening grid v1.0 after seeing validation or test data.
