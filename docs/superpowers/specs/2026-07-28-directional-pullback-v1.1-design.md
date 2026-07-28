# Directional Pullback Scalper v1.1 Design

**Status:** Approved for implementation planning
**Version:** v1.1 research candidate  
**Date:** 28 July 2026  
**Scope:** XAUUSD on the connected FBS demo environment, one declared 60-minute New York session per trading day

## 1. Objective

v1.1 replaces the rejected capped-grid v1.0 candidate with a single-entry
directional pullback scalper. The strategy is built for one hour of daily gold
trading and seeks small, repeatable profits without averaging into adverse
movement.

The core thesis is simple:

1. Establish directional bias from completed higher-timeframe bars.
2. Wait for a pullback inside the selected one-hour session.
3. Enter only after price resumes in the bias direction.
4. Use one position, one structural stop, and one modest target.

v1.1 is not a grid, recovery strategy, martingale, or discretionary execution
framework. It is a frozen research candidate whose only job is to prove or
disprove a cleaner scalping edge before any shadow or demo promotion.

## 2. Evidence Behind the Change

v1.0 failed even when the historical news gate was intentionally bypassed at the
user's request:

- `08:45-09:45` produced only one development basket with negative expectancy.
- `09:30-10:30` produced five development baskets with negative expectancy.
- No v1.0 window passed development, so validation and test remained untouched.

The failure pattern showed that the capped grid was too restrictive and, when it
did trigger, adverse movement after multiple fills damaged expectancy. Earlier
v0.x exploratory artifacts found a few momentum-continuation winners, but all
v0.x variants also failed due to insufficient sample.

v1.1 therefore keeps the one-hour scalping goal but removes the passive ladder.
The new candidate only trades when a completed-bar pullback has already begun to
resume in the planned direction.

## 3. Non-Negotiable Safety Constraints

- Terminal path is exactly `C:\Program Files\FBS MetaTrader 5\terminal64.exe`.
- Server is exactly `FBS-Demo`.
- Symbol is exactly `XAUUSD`.
- Account margin mode must be MT5 retail hedging (`2`) before any demo order is
  allowed.
- Initial application mode is `shadow`.
- One selected 60-minute session per trading day after historical selection.
- At most one trade attempt per selected session.
- At most one open XAUUSD position belonging to v1.1.
- No grid levels, averaging, martingale, recovery entry, opposite hedge, or
  second attempt after a stop, target, timeout, or abort.
- Mode, volume, target, stop, session, and thresholds may not be changed during
  an active session.
- Nominal modeled risk is at most 0.20% of starting-day equity.
- Absolute projected loss including reserve is at most 0.25% of starting-day
  equity.
- Existing XAUUSD positions or orders block startup.
- Current-date source-backed news confirmation is mandatory for shadow/demo
  eligibility.
- Any high-impact USD or gold news blackout overlapping the selected session
  blocks shadow/demo operation.
- All open positions are force-closed no later than minute 60 of the selected
  session.

Historical exploratory runs may use an explicitly labeled news bypass only to
diagnose raw strategy behavior. A news-bypass run cannot promote v1.1 to shadow
or demo.

## 4. Research Partitions and Session Candidates

v1.1 uses the existing chronological partitions:

- Development: 2 January 2020 through 29 November 2023.
- Validation: 30 November 2023 through 24 March 2025.
- Test: 25 March 2025 through 15 July 2026.

All time conversion uses `America/New_York`.

Development may compare these candidate New York windows:

- `08:45-09:45`
- `09:30-10:30`
- `10:00-11:00`

The added `10:00-11:00` candidate is included because v1.0's first two windows
were too sparse and often failed bias/structure gates. Development is allowed to
evaluate candidate windows. Validation may only evaluate windows that passed the
development gate. Test may only evaluate the single window selected by
validation.

No validation or test result may be used to change a v1.1 threshold.

## 5. Bias

Bias is calculated from completed H1 and M15 bars only. No incomplete bar may be
used for bias.

Bullish bias requires all of:

1. Last completed H1 close is above H1 EMA(20).
2. H1 EMA(20) is above its value three completed H1 bars earlier.
3. Last completed M15 close is above M15 EMA(20).
4. M15 EMA(20) is above its value three completed M15 bars earlier.

Bearish bias is symmetrical:

1. Last completed H1 close is below H1 EMA(20).
2. H1 EMA(20) is below its value three completed H1 bars earlier.
3. Last completed M15 close is below M15 EMA(20).
4. M15 EMA(20) is below its value three completed M15 bars earlier.

If H1 and M15 disagree, the session is neutral and no trade may be armed.

Bias is locked at session start. It may not be refreshed to justify a new trade
inside the same hour.

## 6. Pullback Setup

After bias is locked, v1.1 waits for a pullback on completed M5 bars.

For a bullish setup:

- Price must trade back toward M5 EMA(20) or the most recent completed M5
  breakout level.
- The pullback low must remain above the structural stop candidate.
- The pullback distance from the pre-pullback swing high must be at least
  `0.25 ATR(14)` and no more than `1.10 ATR(14)`.

For a bearish setup:

- Price must trade back toward M5 EMA(20) or the most recent completed M5
  breakdown level.
- The pullback high must remain below the structural stop candidate.
- The pullback distance from the pre-pullback swing low must be at least
  `0.25 ATR(14)` and no more than `1.10 ATR(14)`.

ATR is M5 ATR(14), calculated only from completed bars before the trigger bar
closes. A missing or nonpositive ATR rejects the setup.

## 7. Continuation Trigger

Entry requires completed-bar continuation after the pullback. v1.1 tests trigger
variants on development only:

- M1 close continuation.
- M5 close continuation.

The M1 bullish trigger requires:

- A completed M1 close above the high of the prior completed M1 bar.
- The completed M1 candle body is at least 35% of its full range.
- The close is above M1 EMA(9).

The M1 bearish trigger is symmetrical.

The M5 bullish trigger requires:

- A completed M5 close above the high of the prior completed M5 bar.
- The completed M5 candle body is at least 35% of its full range.
- The close is above M5 EMA(9).

The M5 bearish trigger is symmetrical.

The executable entry is taken on the first tick after the completed trigger bar
is available:

- Long entry uses ask.
- Short entry uses bid.

No entry is allowed after minute 45 of the selected session.

## 8. Stop, Target, and Exit

For a long trade, the initial stop is below the pullback swing low by:

```text
max(0.10 ATR, 2 × reference_spread)
```

For a short trade, the initial stop is above the pullback swing high by the same
buffer.

The trade is rejected when:

- stop distance is less than `0.35 ATR`;
- stop distance is greater than `1.50 ATR`;
- stop violates broker minimum distance;
- spread at entry exceeds the selected spread ceiling;
- projected volume is below broker minimum; or
- projected absolute loss including reserve exceeds 0.25% of starting-day
  equity.

Development may compare fixed target candidates:

- `0.35R`
- `0.50R`
- `0.65R`

Targets are intentionally modest. A larger target is outside v1.1 scope because
the goal is small one-hour scalping, not a large continuation swing.

Exit reasons:

- `TARGET_CLOSED`
- `STOPPED`
- `MOMENTUM_ABORT`
- `SPREAD_ABORT_BEFORE_ENTRY`
- `ENTRY_TIMEOUT`
- `SESSION_FLATTENED`
- `NEWS_BLOCKED`
- `EXISTING_EXPOSURE`
- `RECONCILIATION_REQUIRED`

Momentum abort occurs before target/stop when a completed M1 or M5 close crosses
back through EMA(9) against the trade direction after entry. Historical
research compares M1-abort and M5-abort variants on development only.

Any still-open trade is closed on the last executable tick before minute 60.

## 9. Sizing and Margin

Sizing uses the same cash-risk discipline as v1.0:

```text
raw_volume = nominal_risk_cash / modeled_stop_loss_for_one_lot
```

Volume is floored to broker step size. After rounding, the system recalculates
worst-case cash loss from executable entry to stop and adds the configured
reserve.

Reject the trade when:

- rounded volume is below broker minimum;
- volume violates broker step or maximum;
- projected loss exceeds 0.25% of starting-day equity;
- projected margin exceeds 10% of free margin;
- symbol contract data is unavailable; or
- another XAUUSD position/order exists.

There is no position scaling in v1.1.

## 10. Spread, News, and Broker Preconditions

Reference spread is the median bid/ask spread during the 30 minutes before the
session. Session spread ceiling is selected from development observations and
then frozen for validation/test.

Pre-entry spread must be no greater than:

```text
min(development_selected_spread_ceiling, reference_spread × 2.0)
```

News handling remains strict:

- Empty news files do not confirm a date.
- A `NO_HIGH_IMPACT_EVENTS` row must explicitly cover the selected session for a
  source-backed run.
- High-impact `USD`, `XAU`, `GOLD`, or `ALL` events overlapping the selected
  session block the session.
- News-bypass rows must be visibly labeled and cannot promote a candidate.

## 11. Tick-Level Backtesting

The simulator uses canonical Tickstory bid/ask ticks:

- Long entries use ask.
- Short entries use bid.
- Long exits use bid.
- Short exits use ask.
- A completed trigger bar is only tradable on ticks after that bar's close time.
- If target and stop are both touched on the same tick, the conservative result
  is stop first.
- If momentum abort and target are both detectable at the same completed-bar
  boundary, target wins only when executable price had already reached target
  before the abort decision became available.
- Session force-close uses the last executable tick before minute 60.

Backtest reports trade-level rows, rejection rows, stress rows, and
partition-level summaries.

## 12. Development Search Space

Development-only candidates may vary:

- Session window: `08:45-09:45`, `09:30-10:30`, `10:00-11:00`.
- Trigger timeframe: M1 or M5.
- Target R: `0.35`, `0.50`, `0.65`.
- Momentum abort timeframe: M1 or M5.

All other rules are fixed for v1.1. Validation and test cannot be used to add
new candidate values.

## 13. Research Gates

Development viability requires:

- at least 100 completed trades;
- positive net expectancy after executable bid/ask prices;
- profit factor above 1.15;
- positive expectancy under 1.25× spread;
- positive expectancy after additional 0.05R cost stress;
- maximum drawdown no greater than 8R;
- no calendar year contributing more than 35% of trades;
- no individual stressed trade losing worse than `-1.10R`; and
- bootstrap 90% lower expectancy bound no worse than `-0.05R`.

Validation selects one candidate using:

```text
stressed_expectancy - standard_error
```

Validation requires:

- at least 30 completed trades;
- positive net expectancy;
- profit factor above 1.10;
- positive expectancy under 1.25× spread;
- maximum drawdown no greater than 8R; and
- no individual stressed trade losing worse than `-1.10R`.

Test promotion requires:

- at least 20 completed trades;
- positive net expectancy;
- profit factor above 1.10;
- positive expectancy under 1.25× spread;
- maximum drawdown no greater than 8R; and
- bootstrap 90% lower expectancy bound no worse than `-0.05R`.

A test failure retires v1.1. It does not authorize test-driven tuning.

## 14. Shadow and Demo Promotion

Historical success does not enable trading.

If v1.1 passes test, the system creates a locked shadow config for the single
selected candidate. Shadow mode must then complete at least ten eligible
sessions with:

- no order submission;
- exact offline replay parity;
- zero duplicate events;
- zero incomplete-candle decisions;
- correct session timeout and force-flat simulation;
- source-backed current-date news confirmation; and
- no unexplained difference between simulated and broker-observable prices.

Demo mode requires explicit user-reviewed configuration approval after shadow
evidence is documented. The first demo stage keeps one trade attempt per session
and 0.25% absolute risk.

Automatic return to shadow occurs when:

- rolling 40-trade net expectancy is negative;
- observed drawdown breaches the historical envelope;
- reconciliation is ambiguous;
- broker symbol/account properties change;
- spread behavior exceeds the historical envelope; or
- current-date news confirmation is missing.

## 15. Components and Boundaries

Implementation should add isolated v1.1 components instead of modifying v1.0
grid semantics:

- `pullback_config.py`: immutable v1.1 configuration and candidate values.
- `pullback_models.py`: bias, setup, trigger, trade, and rejection models.
- `pullback_bias.py`: completed H1/M15 bias logic.
- `pullback_setup.py`: completed-bar pullback and trigger detection.
- `pullback_backtest.py`: tick-level one-position simulator.
- `pullback_metrics.py`: expectancy, stress, concentration, and gate metrics.
- `pullback_pipeline.py`: development, validation, test orchestration and
  artifacts.

Existing v1.0 grid modules remain immutable evidence. v1.1 may reuse generic
utilities such as indicators, Tickstory parquet loading, news decisions,
contract-aware sizing helpers, and read-only MT5 access.

Live/shadow/demo execution modules are not created until a v1.1 historical
candidate passes all gates.

## 16. Required Artifacts

Research produces versioned artifacts:

```text
config/pullback-v1.1.json
artifacts/reports/pullback-v1.1-development.csv
artifacts/reports/pullback-v1.1-validation.csv
artifacts/reports/pullback-v1.1-test.csv
artifacts/reports/pullback-v1.1-trades.csv
artifacts/reports/pullback-v1.1-rejections.csv
artifacts/reports/pullback-v1.1-stress.csv
artifacts/reports/pullback-v1.1-summary.json
docs/research/pullback-v1.1-result.md
```

No v1.1 artifact may overwrite v0.x or grid v1.0 evidence.

## 17. Explicit Exclusions

v1.1 does not include:

- grid entries;
- averaging down;
- multiple entries after the first trade;
- recovery orders;
- opposite-direction hedging;
- discretionary exits;
- trailing stops;
- adaptive target selection after validation/test;
- live/real account support;
- automatic demo promotion; or
- parameter optimization using validation or test results.
