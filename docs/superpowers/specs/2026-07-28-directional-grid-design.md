# Directional Capped-Grid Design

**Status:** Approved concept; written specification awaiting final user review  
**Version:** v1.0 research candidate  
**Date:** 28 July 2026  
**Scope:** XAUUSD on the connected FBS demo environment, one declared 60-minute session per trading day

## 1. Objective

Replace the rejected v0.x sweep/reclaim strategy with a bias-driven, capped
three-level entry ladder designed for small basket profits during one trading
hour. The bias is the trade thesis. The grid is only the entry mechanism.

This is not a neutral grid, recovery grid, martingale, or continuously recentered
grid. One grid is one basket and one planned risk event.

Success means positive net expectancy after executable bid/ask prices and cost
stress. A high win rate or a sequence of small winners does not qualify as an
edge unless the full loss distribution remains acceptable.

## 2. Non-Negotiable Safety Constraints

- Terminal: `C:\Program Files\FBS MetaTrader 5\terminal64.exe`.
- Server: exactly `FBS-Demo`.
- Symbol: `XAUUSD`.
- Account mode: MT5 retail hedging. Any other margin mode blocks grid execution.
- Initial application mode: `shadow`.
- Exactly one 60-minute session per day after historical window selection.
- At most one grid cycle per session.
- At most three same-direction entry levels.
- Equal volume at all three levels in v1.0.
- No opposite-direction hedge.
- No size escalation, martingale, recovery order, fourth level, recentering, or
  stop widening.
- Nominal modeled basket risk is at most 0.20% of starting-day equity.
- An additional 0.05% cash reserve is held for spread expansion and slippage.
- Absolute projected basket loss must not exceed 0.25% of starting-day equity.
- All pending orders are cancelled after minute 45.
- Every position is closed no later than minute 60.
- A stopped basket ends trading for the day.
- Missing current-date news confirmation blocks demo execution.

The existing v0.x code and artifacts remain immutable evidence. v1.0 receives
new configuration, reports, strategy code, tests, and magic/comment identifiers.

## 3. Session Candidates and Data Partitions

Research compares the existing declared New York windows:

- `08:45-09:45`
- `09:30-10:30`

All daylight-saving conversion uses `America/New_York`.

The fixed chronological partitions remain:

- Development: 2 January 2020 through 29 November 2023.
- Validation: 30 November 2023 through 24 March 2025.
- Test: 25 March 2025 through 15 July 2026.

The v1.0 architecture and frozen values are evaluated first on development.
Validation may select one of the two windows. The selected window is then
evaluated once on the test tail. No v1.0 test result may be used to change a
threshold.

## 4. Bias

Bias is calculated once immediately before the session from completed M15 bars
and remains locked for the full hour.

Bullish bias requires all of:

1. The last completed M15 close is above EMA(20).
2. EMA(20) is higher than it was three completed M15 bars earlier.
3. The latest completed M15 bar has a higher high and higher low than the prior
   completed M15 bar.

Bearish bias is symmetrical. Otherwise the session is neutral and no grid is
armed.

Changing or refreshing bias after orders are armed is prohibited in v1.0.

## 5. Anchor, ATR, Spread, and Structural Invalidation

At the session opening tick:

- A bullish anchor is the executable ask.
- A bearish anchor is the executable bid.
- Volatility is M5 ATR(14), calculated only from completed pre-session bars.
- Reference spread is the median bid/ask spread during the 30 minutes before
  session start.
- A spread ceiling is the smaller of the historically selected 90th-percentile
  session spread and the configured absolute broker threshold.

The structural reference is the latest confirmed five-bar M5 pivot within the
12 completed M5 bars before session start. A pivot is confirmed only after two
bars have completed on its right.

For a bullish grid:

- Reference pivot is the most recent confirmed swing low.
- Stop is below that pivot by `max(0.10 ATR, 2 × reference spread)`.

For a bearish grid:

- Reference pivot is the most recent confirmed swing high.
- Stop is above that pivot by the same buffer.

Let `D` be the absolute distance from executable anchor to stop. Reject the
session if:

- no confirmed pivot exists;
- ATR is missing or nonpositive;
- `D < 0.60 ATR`;
- `D > 1.50 ATR`;
- current spread exceeds the spread ceiling; or
- broker minimum-distance rules make any entry, stop, or target invalid.

The session is also rejected when confirmed high-impact USD or gold news
blackout data overlaps any part of the 60-minute window, including the
configured pre/post-event buffer. An empty file is not evidence that a date is
clear; each trading date requires an explicit source-backed confirmation.

## 6. Grid Geometry

Three limit entries divide the anchor-to-stop distance:

| Level | Bullish | Bearish |
|---|---:|---:|
| E1 | `anchor - 0.25D` | `anchor + 0.25D` |
| E2 | `anchor - 0.50D` | `anchor + 0.50D` |
| E3 | `anchor - 0.75D` | `anchor + 0.75D` |

Prices are rounded conservatively to the broker tick size. Rounding may not
move an order closer to the stop or increase modeled loss above the cap.

The initial basket profit distance is:

```text
Q = max(0.25D, 4 × reference spread, 2 × current spread)
```

Reject the grid if `Q > 0.40D`; this prevents an abnormally wide spread from
silently converting the design into a large-target strategy.

After one or more entries fill, the common basket target is:

- Long: volume-weighted average entry plus `Q`.
- Short: volume-weighted average entry minus `Q`.

All open legs share the structural stop. Unfilled levels remain unchanged; the
grid is never recentered around the new basket average.

## 7. Sizing and Margin

All three levels are sized before any order is placed. The calculation assumes
that every level fills and every resulting position exits at the common stop.

For one lot at each level, MT5 `order_calc_profit` supplies account-currency
losses `L1`, `L2`, and `L3`. Equal per-level volume is:

```text
raw_volume = nominal_risk_cash / (|L1| + |L2| + |L3|)
```

Volume is floored to the broker step. The system recalculates all three losses
after rounding and adds the configured cash cost/slippage reserve.

The grid is rejected when:

- volume is below the broker minimum;
- any volume violates min, max, or step;
- recalculated worst-case loss exceeds 0.25% of starting-day equity;
- all-level projected margin exceeds 10% of current free margin;
- account, symbol, or contract specifications are unavailable; or
- another XAUUSD position or pending order exists.

No level receives more volume because it is farther from the anchor.

## 8. Order and Basket Lifecycle

The deterministic state machine is:

```text
IDLE
  -> BIAS_LOCKED
  -> GRID_VALIDATED
  -> GRID_ARMED
  -> PARTIALLY_FILLED or FULLY_FILLED
  -> TARGET_CLOSED, STOPPED, TIMED_OUT, or ABORTED
```

Each pending entry is sent with:

- its structural server-side stop;
- a provisional per-leg target at entry price plus/minus `Q`;
- the v1.0 magic number and versioned comment; and
- a unique basket and level identifier.

After fills are reconciled from MT5 trade transactions, the controller computes
the volume-weighted basket target and updates all remaining positions to that
common price. If the controller disconnects before modification, every filled
position still has a protective stop and provisional profit target.

Remaining pending orders are cancelled when:

- the basket target is reached;
- any leg stops;
- a completed M5 close crosses the locked pre-session EMA(20) against the bias;
- current spread breaches the selected ceiling;
- minute 45 is reached; or
- the application cannot reconcile broker state unambiguously.

Existing positions are not closed merely because spread widens. They remain
protected by the structural stop and minute-60 forced exit.

`BIAS_ABORT` is different from a spread-only cancellation: when a completed M5
close crosses the locked pre-session EMA(20) against the bias, the controller
cancels unfilled orders, closes all filled legs at the executable market side,
and ends the basket. It may not arm a replacement grid.

At minute 60, the controller cancels all remaining orders and closes every
position belonging to the basket. An ambiguous order or close result is
journaled and never retried automatically until broker state is reconciled.

## 9. Decision and Rejection Codes

Every eligible session and state transition records a stable code. Required
codes include:

- `NEUTRAL_BIAS`
- `ATR_UNAVAILABLE`
- `NO_CONFIRMED_PIVOT`
- `INVALIDATION_TOO_CLOSE`
- `INVALIDATION_TOO_FAR`
- `SPREAD_TOO_WIDE`
- `NEWS_BLOCKED`
- `BROKER_DISTANCE_INVALID`
- `VOLUME_BELOW_MINIMUM`
- `BASKET_RISK_EXCEEDED`
- `MARGIN_LIMIT_EXCEEDED`
- `EXISTING_EXPOSURE`
- `GRID_ARMED`
- `LEVEL_1_FILLED`
- `LEVEL_2_FILLED`
- `LEVEL_3_FILLED`
- `BIAS_ABORT`
- `TARGET_CLOSED`
- `STOPPED`
- `PENDING_EXPIRED`
- `SESSION_FLATTENED`
- `RECONCILIATION_REQUIRED`

Records include UTC and New York timestamps, bias inputs, ATR, pivot, anchor,
spread statistics, all requested and actual prices, volume, projected loss,
margin, basket average, target, realized P/L, MFE, MAE, and broker results.

## 10. Tick-Level Backtesting

The simulator uses canonical Tickstory bid/ask ticks:

- A long limit fills only when executable ask reaches or passes its price.
- A short limit fills only when executable bid reaches or passes its price.
- Long exits use bid; short exits use ask.
- Limit fills use the executable quote and cannot be modeled at a worse price
  than the requested limit unless an explicit adverse-fill stress is enabled.
- All fills are processed in timestamp order.
- If a gapping tick would both fill a new level and breach its stop, the
  conservative result is a fill followed by a stopped exit on that tick.
- Common basket target changes take effect only after the fill that caused the
  new weighted average.
- All unfilled orders expire at minute 45.
- All open positions exit on the last executable tick before minute 60.

The simulator reports both basket-level and leg-level records. Metrics include
net R, gross R, cost R, expectancy, profit factor, drawdown, consecutive losses,
MFE, MAE, holding time, levels filled, maximum inventory, forced-close rate,
year/month concentration, and results by spread and volatility regime.

Required stress scenarios:

- observed Tickstory bid/ask;
- spread multiplied by 1.25;
- spread multiplied by 1.50;
- an additional 0.05R basket slippage/commission cost;
- delayed basket-controller target modification by one tick; and
- conservative same-tick fill/stop ordering.

## 11. Research Gates

Development viability requires:

- at least 100 completed baskets in each window being considered;
- positive net expectancy after observed bid/ask;
- profit factor above 1.15;
- positive expectancy under 1.25× spread and additional 0.05R cost;
- maximum drawdown no greater than 8R;
- no calendar year contributing more than 35% of baskets; and
- no individual basket losing more than 1.10R under the declared stress model.

Only viable development windows proceed. Validation selects one window using
stressed expectancy penalized by its standard error. Validation requires at
least 30 baskets and the same expectancy, profit-factor, drawdown, concentration,
and tail-loss gates.

The selected window is evaluated once on test. Test promotion requires:

- at least 20 baskets;
- positive net expectancy;
- profit factor above 1.10;
- positive expectancy under 1.25× spread;
- maximum drawdown no greater than 8R; and
- a one-sided 90% bootstrap lower bound for expectancy no worse than `-0.05R`.

A test failure retires v1.0. It does not authorize test-driven tuning.

## 12. Shadow and Demo Promotion

Historical success does not enable trading.

Shadow mode must complete at least ten eligible sessions with:

- no order submission;
- exact offline replay parity;
- zero duplicate events;
- zero incomplete-candle decisions;
- correct order-expiry and forced-flat simulation;
- broker spread and specification calibration; and
- no unexplained difference between simulated and broker-observable prices.

Demo mode then requires an explicit user-reviewed configuration change. The
first demo stage remains one basket per session and 0.25% absolute basket risk.
After at least 40 completed demo baskets, rolling expectancy, drawdown, spread,
fill quality, and rule compliance are reviewed before any recalibration.

Automatic return to shadow occurs when:

- rolling 40-basket net expectancy is negative;
- observed drawdown breaches the historical envelope;
- reconciliation is ambiguous;
- account mode, server, symbol specification, or spread behavior changes; or
- current-date news confirmation is missing.

## 13. Components and Boundaries

Implementation will add isolated v1.0 components:

- `grid_config.py`: immutable grid research and safety configuration.
- `grid_bias.py`: completed-bar bias, pivot, ATR, and grid geometry.
- `grid_models.py`: plans, levels, fills, basket state, and reason codes.
- `grid_backtest.py`: tick-ordered pending-order and basket simulator.
- `grid_metrics.py`: basket metrics, stresses, partitions, and gates.
- `grid_pipeline.py`: development, validation, test, and artifact orchestration.
- `grid_shadow.py`: no-trade live planner and replay journal.
- `grid_execution.py`: hedging-account pending orders, reconciliation, position
  modification, cancellation, and forced close.

The existing read-only MT5 gateway remains incapable of trading. Only
`grid_execution.py` may call order-check, order-send, order-remove, position
modify, or close operations. v0.x execution remains disabled and is not reused
for multi-order basket submission.

## 14. Required Artifacts

Research produces:

```text
config/grid-v1.0.json
artifacts/reports/grid-v1.0-development.csv
artifacts/reports/grid-v1.0-validation.csv
artifacts/reports/grid-v1.0-test.csv
artifacts/reports/grid-v1.0-baskets.csv
artifacts/reports/grid-v1.0-legs.csv
artifacts/reports/grid-v1.0-rejections.csv
artifacts/reports/grid-v1.0-stress.csv
artifacts/reports/grid-v1.0-summary.json
```

Shadow and demo journals are append-only JSONL files with basket and level IDs.
No report may overwrite a v0.x artifact.

## 15. Explicit Exclusions

v1.0 does not include:

- simultaneous long and short grids;
- a second grid after target or stop;
- trailing stops;
- partial discretionary closes;
- martingale or geometric sizing;
- adaptive level count;
- grid recentering;
- weekend holding;
- live/real account support; or
- parameter optimization using validation or test outcomes.
