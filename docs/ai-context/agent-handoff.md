# Agent handoff

## Resume point

Work from `feat/grid-v1-research`. The source-backed research branch has
reached its terminal decision: both frozen strategies are rejected at
development. No shadow or demo work remains for Grid v1.0 or Pullback v1.1.

## Authoritative local artifacts

Canonical Tickstory market data is outside the linked worktree:

```text
D:\Source Codes\Codex\GSCALP\artifacts\market
```

Ignored evidence directories inside the worktree:

```text
artifacts\news\mt5-calendar
artifacts\reports-source-backed-grid-v1.0
artifacts\reports-source-backed-pullback-v1.1
```

Key identities:

- market manifest:
  `3dd947d99b3f5420051fc2c9ea9ff9142bf1416c52a387696319f63e46187c1e`
- canonical news:
  `72c310660954965f13f3394f30273e6a5349647bbce3b6865dba6109be20e26d`
- Grid summary:
  `3af5c548a315948287e91f80f3556f91b675d0eb3462981464c63a116ed2aa55`
- Pullback summary:
  `17acf0407a2e3f82cd526b89c556618a1f7cfd4a70bf07667933077271f320dd`

The MT5 manifest and both research result documents contain the remaining raw,
coverage, and ledger hashes.

## Decision boundary

Do not tune, lock, shadow, or execute either rejected version. Validation and
test stayed unopened. If the user chooses to continue research, the next work
is a separately preregistered v1.2—not a threshold relaxation based on these
results.

The approved terminal remains
`C:\Program Files\FBS MetaTrader 5\terminal64.exe`. The completed export was
read-only, declared `application_can_trade=false`, began with zero XAUUSD
positions/orders, and did not call an order API.

## Verification commands

```powershell
$env:PYTHONPATH='src'
python -m pytest -q
$calendarFiles = @(
  'mt5/GSCALP_NewsExport.mq5',
  'scripts/run_mt5_calendar_export.ps1',
  'src/gscalp/mt5_calendar_normalize.py',
  'src/gscalp/mt5_calendar_raw.py',
  'src/gscalp/mt5_calendar_pipeline.py',
  'src/gscalp/news_coverage.py',
  'src/gscalp/grid_news_coverage.py',
  'src/gscalp/pullback_news_coverage.py'
)
rg -n "order_send|order_check|TRADE_ACTION|ORDER_TYPE_BUY|ORDER_TYPE_SELL|PositionOpen|OrderSend|CTrade" $calendarFiles
git diff --check
Get-FileHash config\grid-v1.0.json -Algorithm SHA256
Get-FileHash config\pullback-v1.1.json -Algorithm SHA256
Get-FileHash data\news_blackouts.csv -Algorithm SHA256
```

The calendar-pipeline order-API scan should return no matches. The separate,
pre-existing guarded execution module is outside this scan. Config hashes must remain
`f7fc276470fbd8ffef8b33800b0d3b67541b411e24e1875c70b7669b06552d2d`
and `2e6aec2cffc6714f907b0bdb5328d1a99c6d14362c56eaa8e4b3a1c783d504b0`.
