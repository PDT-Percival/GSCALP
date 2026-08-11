# Agent handoff

## Resume point

Work from `feat/grid-v1-research`. Pullback v1.1 historical implementation and
performance work are complete through commit `5fb7f81`. The definitive
user-approved no-news run is documented in
`docs/research/pullback-v1.1-result.md` and is rejected at development.

## Authoritative artifacts

The canonical Tickstory market data is outside the linked worktree at:

```text
D:\Source Codes\Codex\GSCALP\artifacts\market
```

The definitive ignored result directory is:

```text
artifacts\reports-news-bypass-pullback-v1.1
```

Before trusting copied artifacts, compare their hashes with the research
result document. The development summary hash is
`e5235ed7f3a380f3191c9566119f4effc78d25345931d389cbe4bad2d07c3259`.

## Exact next work

1. Source and verify a complete, reproducible USD/gold economic-calendar file
   at the schema used by `data/news_blackouts.csv`.
2. Run the news coverage audit and require zero missing date confirmations.
3. Rerun frozen research without changing strategy parameters or spread
   ceilings. Treat any config-hash change as a new version.
4. If no strategy passes, keep shadow/demo gates closed. If a separately
   preregistered future version passes, refresh FBS broker metadata read-only
   before scheduling shadow parity sessions.

## Verification commands

```powershell
$env:PYTHONPATH='src'
python -m pytest -q
Get-ChildItem -Path src\gscalp -Filter 'pullback_*.py' |
  Select-String -Pattern 'order_send|order_check|TRADE_ACTION|ORDER_TYPE_BUY|ORDER_TYPE_SELL'
git diff --check
```

## Do not touch

- Do not reinterpret the broad bypass interval as source-backed news data.
- Do not inspect validation/test to tune pullback v1.1.
- Do not create a locked v1.1 config or enable any order path.
- Do not replace the FBS terminal path; the approved terminal is
  `C:\Program Files\FBS MetaTrader 5\terminal64.exe`.
