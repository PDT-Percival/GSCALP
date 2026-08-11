# Pullback v1.1 historical result

**Decision: REJECTED at the development gate (`development_rejected`).** The
frozen no-news sensitivity run evaluated all 36 candidates. None passed, so no
candidate was selected, validation and test remained unopened, and v1.1 must
not advance to shadow or demo execution.

## Frozen inputs

- Config: `config/pullback-v1.1.json`
- Config SHA-256:
  `2e6aec2cffc6714f907b0bdb5328d1a99c6d14362c56eaa8e4b3a1c783d504b0`
- Canonical market manifest: `artifacts/market/manifest.json`
- Market manifest SHA-256:
  `3dd947d99b3f5420051fc2c9ea9ff9142bf1416c52a387696319f63e46187c1e`
- News input:
  `artifacts/news-bypass/grid-v1.0-user-approved-news-bypass.csv`
- News input SHA-256:
  `3ecdd50c46b51bddadc69836fe2413b8578351af4b77ff4a3608a55653046886`
- Implementation commit: `5fb7f81`
- Output: `artifacts/reports-news-bypass-pullback-v1.1/`
- Completed runtime: 860.0 seconds

The spread ceilings were reused from the source-backed header-only run rather
than retuned after seeing the bypass result.

## Partition access and gate result

The run accessed development only, from `2020-01-02` through `2023-11-29`.
Because zero candidates passed development:

- `development_accessed=true`
- `validation_accessed=false`
- `test_accessed=false`
- `historical_gate_passed=false`
- `promotion_eligible=false`

The highest-expectancy candidate was still negative:

| Candidate | Trades | Base expectancy R | Base PF | Max DD R | Spread-stress expectancy R | +0.05R cost expectancy R | Bootstrap lower R |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 09:30-10:30, M1 trigger, 0.35R target, M5 abort | 73 | -0.016078 | 0.942991 | 6.337352 | -0.061113 | -0.066078 | -0.107380 |

This candidate failed the minimum sample, positive expectancy, profit-factor,
both stress-expectancy, stressed-tail, and bootstrap gates. The top-ranked
candidate with at least 100 trades returned `-0.087189R` expectancy and
`0.647888` profit factor with `11.368526R` maximum drawdown. The rejection is
therefore not explained by one narrowly missed threshold.

## Ledger reconciliation

- Candidate rows: 36
- Base trade rows: 1,896
- Reason-coded rejection rows: 41,772
- Stress metric rows: 108
- Candidate trading dates: 1,213
- Outcomes per candidate: exactly 1,213
- Total candidate-date outcomes: 43,668
- Development gate passes: 0

Base metrics were independently recomputed from the trade ledger, including
trade count, win rate, expectancy, sample deviation/error, profit factor,
maximum drawdown, minimum trade, and maximum year share. The largest absolute
difference from the pipeline report was `7.105427357601002e-15`; there were no
mismatches above `1e-10`.

The largest reason-coded rejection totals across all candidates were:

| Reason | Count |
| --- | ---: |
| neutral_bias | 17,328 |
| no_pullback | 9,246 |
| pullback_too_deep | 8,346 |
| spread_too_wide | 4,728 |
| stop_too_far | 852 |
| trigger_after_cutoff | 480 |

## Data-quality and evidence assessment

The output grain is complete and internally consistent for the approved
no-news run: every candidate-date pair has exactly one base trade or rejection,
all 36 candidates appear in both ledgers, and validation/test files contain
headers only. The canonical manifest and config hashes match the run summary.

The news file is intentionally **not** source-backed. It contains one broad
`NO_HIGH_IMPACT_EVENTS` interval marked
`USER_APPROVED_NEWS_BYPASS_NOT_SOURCE_BACKED_SINGLE_INTERVAL`. Therefore this
run is a sensitivity result, not evidence that historical sessions were clear
of USD or gold-impact news. News filtering could change trade composition, so
the bypass result does not replace the required date-by-date calendar run.

The separate source-backed header-only run conservatively produced 43,668
`news_blocked` outcomes and zero trades because confirmations are still
missing. It proves the news gate fails closed; it does not estimate strategy
performance under verified news exclusions.

## Artifact hashes

| Artifact | SHA-256 |
| --- | --- |
| `pullback-v1.1-development.csv` | `cb009f5bc09c865aa762dcdba7c19b8c72ca20babe05cb66e098757edb53118b` |
| `pullback-v1.1-rejections.csv` | `c54cf8d0113861a35a3c82c9a11f3ae1c1e7957fdf5d4ff9f5c2ac24ce8e2d46` |
| `pullback-v1.1-stress.csv` | `786faf532bf6bca304223e628626baf3ae9c2e3658f86846bb5570bd0498a845` |
| `pullback-v1.1-summary.json` | `e5235ed7f3a380f3191c9566119f4effc78d25345931d389cbe4bad2d07c3259` |
| `pullback-v1.1-trades.csv` | `f1afa67e42ab5c4f83137a3f1ff39acb46c542a23a054d6665a2618ce817f0f0` |
| header-only validation/test CSVs | `c9b7f327c56ee4374e746e9ea50e58a1efe9b4812875b87356cc8a675907d85d` |

## Safety decision and next step

Keep order submission disabled. Do not start the ten-session shadow gate for
v1.1, do not create a locked candidate, and do not tune v1.1 using validation
or test. Complete the source-backed USD/gold news confirmations for the
required evidence record. If strategy research continues, preregister a
separately versioned v1.2 hypothesis and gates before running it.
