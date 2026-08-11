# Current status

- Branch: `feat/grid-v1-research`
- Pull request: `https://github.com/PDT-Percival/GSCALP/pull/1`
- MT5 calendar/export implementation: through commit `c2e84af`
- Safety state: historical/read-only; no strategy is eligible for shadow or
  demo execution.

## Evidence now available

The approved FBS MT5 terminal exported a complete source-backed USD/XAU
economic calendar in a guarded, read-only run. Import and independent
reconciliation confirmed:

- 158 successful monthly queries (79 USD, 79 XAU), zero query errors;
- 24,596 unique raw event rows;
- 8,098 canonical news rows (3,419 high impact, 4,679 explicit clear);
- complete coverage for 4,056 Grid v1.0 sessions and 6,084 Pullback v1.1
  sessions;
- exact generated/independent coverage agreement; and
- canonical news SHA-256
  `72c310660954965f13f3394f30273e6a5349647bbce3b6865dba6109be20e26d`.

The approved terminal is
`C:\Program Files\FBS MetaTrader 5\terminal64.exe`; the manifest records
terminal build 6090, `FBS-Demo`, trade mode 0, margin mode 2, and
`application_can_trade=false`.

## Research decision

Grid v1.0 and Pullback v1.1 were rerun from their unchanged frozen configs
using the source-backed calendar. Both are `development_rejected`:

- Grid: both candidate windows failed; the better window produced one basket
  with `-0.030645R` base and `-0.103207R` stressed expectancy.
- Pullback: 0 of 36 candidates passed. The top score was based on only four
  base trades and one spread-stress trade, so it failed robustness gates.

Validation and test stayed unopened for both strategies. The ten-session
shadow gate and 0.25% demo stage were correctly skipped because promotion
eligibility was false. No GSCALP order API was called and no order was
submitted by this workflow.

Definitive results are in `docs/research/grid-v1.0-result.md` and
`docs/research/pullback-v1.1-result.md`.
