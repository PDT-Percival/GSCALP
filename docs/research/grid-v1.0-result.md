# Grid v1.0 source-backed historical result

**Decision: REJECTED at the development gate (`development_rejected`).** The
frozen Grid v1.0 configuration was rerun without tuning after complete
source-backed MT5 USD/XAU calendar coverage became available. Neither candidate
session passed development, so no window was selected and validation, test,
shadow, and demo execution remained closed.

## Frozen inputs and evidence

- Config: `config/grid-v1.0.json`
- Config SHA-256: `f7fc276470fbd8ffef8b33800b0d3b67541b411e24e1875c70b7669b06552d2d`
- Canonical market manifest SHA-256:
  `3dd947d99b3f5420051fc2c9ea9ff9142bf1416c52a387696319f63e46187c1e`
- Canonical news: `data/news_blackouts.csv`
- Canonical news SHA-256:
  `72c310660954965f13f3394f30273e6a5349647bbce3b6865dba6109be20e26d`
- MT5 calendar manifest: `artifacts/news/mt5-calendar/manifest.json`
- Research output: `artifacts/reports-source-backed-grid-v1.0/`
- Summary SHA-256:
  `3af5c548a315948287e91f80f3556f91b675d0eb3462981464c63a116ed2aa55`

The guarded exporter used the approved
`C:\Program Files\FBS MetaTrader 5\terminal64.exe` terminal on `FBS-Demo` in
read-only mode. It completed 158 unique monthly queries (79 USD and 79 XAU),
with zero query errors and 24,596 unique raw calendar rows. The normalized news
file has 8,098 rows: 3,419 high-impact event rows and 4,679 explicit clear
coverage rows.

The Grid coverage audit evaluated all 4,056 candidate sessions through
2026-07-15: 3,156 were clear and 900 overlapped a blackout. Coverage was
complete and ready. An independently generated audit matched the canonical
coverage result by `(local_date, window, code)`.

## Development result

Only the locked development partition, 2020-01-02 through 2023-11-29, was
accessed. Validation (2023-11-30 through 2025-03-24) and test (2025-03-25
through 2026-07-15) were not accessed.

| NY session | Baskets | Base expectancy R | Base PF | Base max DD R | Stressed expectancy R | Stressed PF | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 08:45-09:45 | 1 | -0.030645 | 0.000000 | 0.030645 | -0.103207 | 0.000000 | Failed |
| 09:30-10:30 | 4 | -0.391437 | 0.216896 | 1.999412 | -0.457642 | 0.154760 | Failed |

Both windows have negative base and stressed expectancy and far too little
eligible activity for a stable one-hour strategy. The source-backed exclusions
were active: 553 development outcomes were rejected as `news_blocked`; other
major rejection reasons were `neutral_bias` (781), `invalidation_too_far`
(553), and `spread_too_wide` (445).

## Artifact ledger

| Artifact | Rows | SHA-256 |
| --- | ---: | --- |
| `grid-v1.0-development.csv` | 2 | `7dae3f582ce1e907b9c6c0f6e0d71413baa669daf5e2007512ac37dfae57a384` |
| `grid-v1.0-baskets.csv` | 5 | `440b9bd9d64401578bd18f3b2c8b2eb6752a5ec04b6cad6fc5c21e037a13656a` |
| `grid-v1.0-legs.csv` | 10 | `d03fba8ba1f9199b3c270d06802cca5b73e6699b4841fb0533a70a3af3d17288` |
| `grid-v1.0-rejections.csv` | 2,421 | `375786a2c98c5156c2bdf33f4177a5a8c8443cffef1d52e796b1a780b7c290d7` |
| `grid-v1.0-stress.csv` | 12 | `c4cfcb9df90c690f2eec6291b9de2ec2a1e5c465da578fb7f5a36ce53e142a30` |
| `grid-v1.0-summary.json` | - | `3af5c548a315948287e91f80f3556f91b675d0eb3462981464c63a116ed2aa55` |

The validation and test CSVs contain headers only and share SHA-256
`1af9296ffa989813c4fbc784dcf3b19268d6f69d3722eba8bdd08f64861d4cb7`.

## Safety decision

Do not create `config/grid-v1.0-locked.json`, start the ten-session shadow
gate, or enable demo execution. The export and research paths were read-only;
the exporter declared `application_can_trade=false`, the account precondition
showed zero XAUUSD positions and orders, and no GSCALP order API was called.

Any continued research must be a separately preregistered strategy version,
not tuning against validation or test and not a relaxed reinterpretation of
Grid v1.0.
