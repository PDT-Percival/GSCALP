# Pullback v1.1 source-backed historical result

**Decision: REJECTED at the development gate (`development_rejected`).** The
already frozen Pullback v1.1 design was rerun without tuning against complete,
source-backed MT5 USD/XAU calendar coverage. All 36 candidates failed; no
candidate was selected, and validation, test, shadow, and demo execution
remained closed.

## Frozen inputs and evidence

- Config: `config/pullback-v1.1.json`
- Config SHA-256:
  `2e6aec2cffc6714f907b0bdb5328d1a99c6d14362c56eaa8e4b3a1c783d504b0`
- Canonical market manifest SHA-256:
  `3dd947d99b3f5420051fc2c9ea9ff9142bf1416c52a387696319f63e46187c1e`
- Canonical news: `data/news_blackouts.csv`
- Canonical news SHA-256:
  `72c310660954965f13f3394f30273e6a5349647bbce3b6865dba6109be20e26d`
- MT5 calendar manifest: `artifacts/news/mt5-calendar/manifest.json`
- Research output: `artifacts/reports-source-backed-pullback-v1.1/`
- Summary SHA-256:
  `17acf0407a2e3f82cd526b89c556618a1f7cfd4a70bf07667933077271f320dd`

The guarded exporter completed 158 unique monthly queries (79 USD and 79
XAU), with zero query errors and 24,596 unique raw rows. The Pullback coverage
audit evaluated all 6,084 candidate sessions through 2026-07-15: 4,679 were
clear and 1,405 overlapped a high-impact blackout. Coverage was complete and
ready, and an independent audit matched the canonical result exactly by
`(local_date, window, code)`.

## Partition access and gate result

The run accessed development only, from 2020-01-02 through 2023-11-29:

- `development_accessed=true`
- `validation_accessed=false`
- `test_accessed=false`
- `historical_gate_passed=false`
- `promotion_eligible=false`
- development candidates: 36; gate passes: 0

The highest selection score came from
`08:45-09:45__M5__0.65R__abort_M5`, but it had only four base trades:

| Base trades | Base expectancy R | Base PF | Max DD R | Cost-stress expectancy R | Spread-stress trades | Bootstrap lower R | Gate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4 | 0.368383 | 3.847725 | 0.517442 | 0.318383 | 1 | 0.069380 | Failed |

That apparent positive result is not usable evidence: half of the four base
trades came from one year, and spread stress retained a single trade with 100%
year concentration. It fails the frozen sample and robustness requirements.
The broader candidate set also provides no alternative: all 36 frozen gate
booleans are false.

The source-backed filter materially reduced eligible outcomes. Across all
candidates the largest rejection counts were `neutral_bias` (13,320),
`news_blocked` (10,500), `no_pullback` (6,546), `pullback_too_deep` (5,724),
and `spread_too_wide` (4,728).

## Artifact ledger

| Artifact | Rows | SHA-256 |
| --- | ---: | --- |
| `pullback-v1.1-development.csv` | 36 | `2b7bb099eddaa68f8367f139a7c99a209cefe1ef568e02d17ca1e323f7007c96` |
| `pullback-v1.1-trades.csv` | 1,416 | `fa866ac41cd2ae4e332b453d168639dd1bcdb57418a8040d345ce5e76873677d` |
| `pullback-v1.1-rejections.csv` | 42,252 | `34a4cdc3ae013bba16b1a862fa17ed1e1b207ec1d3d4e02a98a2fa794f34b190` |
| `pullback-v1.1-stress.csv` | 108 | `e7be5211199a3fb15c79d5a250cea494ec9685ee2b27b356d91bdb5832bcf1f0` |
| `pullback-v1.1-summary.json` | - | `17acf0407a2e3f82cd526b89c556618a1f7cfd4a70bf07667933077271f320dd` |

The validation and test CSVs contain headers only and share SHA-256
`c9b7f327c56ee4374e746e9ea50e58a1efe9b4812875b87356cc8a675907d85d`.

## Safety decision and next step

Do not create a locked Pullback v1.1 candidate, begin the ten-session shadow
gate, or enable demo execution. The export and research paths were read-only;
the exporter declared `application_can_trade=false`, the account precondition
showed zero XAUUSD positions and orders, and no GSCALP order API was called.

The earlier user-approved no-news run remains sensitivity evidence only and is
superseded for the promotion decision by this source-backed result. If research
continues, preregister a distinct v1.2 hypothesis and its gates before any new
development run. Do not tune v1.1 against unopened validation or test data.
