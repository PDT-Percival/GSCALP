# GSCALP Operations and Recalibration

## Objective and safety state

GSCALP is a one-hour-per-day XAUUSD research system. Its objective is positive
expectancy after executable bid/ask costs with small, repeatable risk—not a high
win rate or an occasional large payout. The only permitted account is
`FBS-Demo` through:

```text
C:\Program Files\FBS MetaTrader 5\terminal64.exe
```

The committed configuration is `shadow`. Read-only research and shadow code
cannot submit orders. Demo execution is isolated in `execution.py` and requires
all historical, shadow, news, account, session, spread, position, sizing, and
risk gates to pass.

## Signal and trade rationale

Version 0.1 trades only when all of these facts are present on completed bars:

1. M15 trend agrees: price relative to EMA(20), three-bar EMA slope, and the
   latest high/low structure all point in the same direction.
2. Price sweeps a completed previous-day, Asian, or London liquidity level by
   0.15–0.50 M5 ATR(14).
3. An M5 candle reclaims the level within two bars.
4. A directional body of at least 0.50 ATR closes through the prior three-bar
   micro swing.
5. Price retests the level or displacement retracement zone within three bars.
6. The stop beyond the sweep is at most 0.80 ATR and the next opposing level
   leaves at least 1.20R of room.
7. Entry occurs on the next bar at executable ask for a long or bid for a short;
   the target is the nearer of 1.40R and opposing liquidity.

Every completed bar produces a stable rejection or qualification code. No
averaging, martingale, grid, stop widening, or overnight position is allowed.

## Reproducible commands

```powershell
python -m gscalp.cli doctor --config config/strategy.json
python -m gscalp.cli backtest --config config/strategy.json --walk-forward
python -m pytest -q
```

Read-only broker downloads can be made with:

```powershell
python -m gscalp.cli download --config config/strategy.json --days 180 --timeframes M1 M5 M15 H1
```

Raw Tickstory CSV files are immutable. Canonical parquet data and generated
reports live under `artifacts/`.

## Version 0.1 result and current decision

The frozen rules evaluated 3,366 candidate sessions from 2 January 2020 through
15 July 2026. They produced one qualified signal. That trade returned +1.43R,
but one observation is statistically unusable. Therefore:

- v0.1 status is `failed_insufficient_sample`;
- no one-hour window is selected;
- historical, shadow, and demo gates remain closed;
- the win does not justify trading or parameter approval.

The development partition ends 29 November 2023; validation ends 24 March 2025;
the remaining dates are the test tail. Window and threshold choices may not use
the test tail.

## Recalibration protocol

Diagnose in this order: data integrity, broker costs, backtest/live parity,
execution discipline, market regime, then strategy thresholds. A code defect is
fixed without relabeling it as strategy improvement.

For the next research version:

1. Copy the configuration to a new version; never edit v0.1 results in place.
2. State one hypothesis before running it. The first supported hypothesis is
   that the 0.50-ATR maximum sweep cap is too restrictive: development-only
   rejected sweeps had a median depth near 1.39 ATR.
3. Change only `sweep_atr_max` for that experiment. Do not simultaneously alter
   trend, reclaim, displacement, retest, stop, target, session, or risk rules.
4. Examine development data first. Reject the experiment if it still cannot
   produce at least 30 development-plus-validation trades or if performance is
   dominated by a few dates.
5. If development is viable, evaluate both declared windows on validation and
   select one without consulting test performance.
6. Evaluate the selected window once on the test tail. Require positive net
   expectancy, profit factor above 1.10, and maximum drawdown no greater than
   8R under bid/ask data and additional 0.05R, 0.10R, and 0.20R cost stress.
7. Lock the chosen session and parameters before shadow monitoring.

After deployment, review rule compliance daily and data/fill anomalies weekly.
Do not change a live strategy until at least 40 qualified forward trades exist.
Change one parameter or filter at a time and return to shadow automatically if
rolling 40-trade net expectancy is negative or drawdown breaches the historical
envelope.

## Promotion gates

Demo mode requires all of the following:

- positive net expectancy on the selected untouched test partition;
- profit factor greater than 1.10 after costs;
- historical drawdown within 8R;
- at least ten clean eligible shadow sessions with replay parity;
- confirmed current-date UTC news data;
- an explicit manual configuration change from `shadow` to `demo`.

Until then, `data/news_blackouts.csv` intentionally contains no current-date
confirmation and blocks execution. Never fabricate a no-news row to bypass it.

## Current grid and pullback research decision

Grid v1.0 and directional pullback v1.1 are both rejected at development.
Pullback v1.1 evaluated 36 frozen candidates over 1,213 development dates under
the user-approved no-news sensitivity condition. Zero candidates passed; the
best returned `-0.016078R` base expectancy, `0.942991` profit factor, and 73
trades. Validation and test remained unopened.

Do not begin the ten-session shadow gate or demo execution for v1.1. The broad
news-bypass interval is not source-backed and is non-promotable. The exact
evidence, hashes, reconciliation, and limitations are recorded in
`docs/research/pullback-v1.1-result.md`.

Risk in demo is 0.25% of starting-day equity per trade, at most two entries, and
at most 0.50% total session risk/loss. Volume is floored to the broker step from
`order_calc_profit`; any rounding that exceeds the cash cap is rejected. Each
submission is preflighted and journaled, and ambiguous failures are never
retried automatically.
