# MT5 Gold Scalper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a broker-aware, testable XAUUSD system that studies one fixed 60-minute session, logs every signal and reason, and permits tightly guarded execution only on the connected FBS demo account after validation gates pass.

**Architecture:** A read-only MT5 gateway supplies broker specifications, bars, ticks, and trade history. A pure strategy engine converts completed bars into reason-coded signals, and a cost-aware backtester evaluates them without connecting to MT5. Shadow monitoring uses the same engine live; order execution is isolated behind a second gateway and remains disabled until explicit acceptance gates are satisfied.

**Tech Stack:** Python 3.14, MetaTrader5 5.0.5735, pandas, NumPy, pytest, standard-library `zoneinfo`, JSON/CSV artifacts.

## Global Constraints

- Terminal path is exactly `C:\Program Files\FBS MetaTrader 5\terminal64.exe`.
- Account server must equal `FBS-Demo`; any other server aborts startup.
- Symbol is `XAUUSD`; contract specifications must be read from MT5, never hard-coded for sizing.
- Initial execution mode is `shadow`; no call to `order_send` is reachable in read-only or shadow mode.
- Session length is exactly 60 minutes. Historical research may compare a small declared set of candidate New York-time windows, but one window must be locked before forward testing.
- Initial risk is 0.25% of starting-day equity per trade, maximum two entries, and maximum 0.50% starting-day equity loss per session.
- No averaging down, martingale, grid, widening stops, or positions held after the session.
- Signals use only completed candles; no look-ahead data is permitted.
- Backtests include spread and commission where available and report results in net R.
- Missing news-blackout data for the current trading date blocks demo execution.

---

## File Structure

```text
pyproject.toml                         Package metadata and test configuration
config/strategy.json                  Versioned strategy and safety parameters
data/news_blackouts.csv               UTC event windows; required for execution
src/gscalp/config.py                  Typed configuration loading and validation
src/gscalp/models.py                  Bars, signals, trades, and reason codes
src/gscalp/mt5_read.py                Read-only terminal adapter
src/gscalp/indicators.py              EMA, ATR, session-level calculations
src/gscalp/strategy.py                Deterministic signal state machine
src/gscalp/backtest.py                Bid/ask-aware fill simulation
src/gscalp/metrics.py                 Expectancy, drawdown, MFE/MAE, regime slices
src/gscalp/shadow.py                  Live signal logger with no trade permission
src/gscalp/execution.py               Demo-only sizing and order gateway
src/gscalp/cli.py                     Commands for doctor, download, backtest, shadow
tests/                                Unit and integration tests
artifacts/                            Generated market data, signals, and reports
```

## Locked Strategy v0.1

The setup is **trend-aligned liquidity sweep, reclaim, displacement, and retest**:

1. M15 context is bullish only when the last completed close is above EMA(20), EMA slope over three completed bars is positive, and the last confirmed swing structure is higher-low/higher-high. Bearish is symmetric. Otherwise the regime is neutral and no trade is allowed.
2. Eligible liquidity levels are previous-day high/low, completed Asian-session high/low, and completed London-session high/low. Session definitions are expressed in UTC in the configuration and converted from broker timestamps before calculation.
3. A sweep must penetrate an eligible level by 0.15–0.50 of the M5 ATR(14). Smaller breaches are noise; deeper breaches are treated as accepted breakouts.
4. A reclaim requires an M5 close back through the swept level within two completed M5 bars.
5. Displacement requires a completed M5 body of at least 0.50 ATR and a close through the most recent three-bar micro swing in the trend direction.
6. Retest must occur within three completed M5 bars and touch either the reclaimed level or the 50%–75% retracement zone of the displacement body without closing beyond the sweep extreme.
7. Entry is simulated at the next bar's ask for longs or bid for shorts. The stop is one current spread beyond the sweep extreme. The candidate is rejected if stop distance exceeds 0.80 ATR or if the nearest opposing liquidity level offers less than 1.20R.
8. Initial target is the nearer of 1.40R and the next opposing liquidity level. No partial close or automatic breakeven is used in v0.1.

The thresholds above are hypotheses, not claimed edges. They remain unchanged for the first research run and are changed one at a time only through walk-forward evaluation.

---

### Task 1: Project Bootstrap and Safety Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `config/strategy.json`
- Create: `data/news_blackouts.csv`
- Create: `src/gscalp/__init__.py`
- Create: `src/gscalp/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(path: Path) -> StrategyConfig`
- Produces: immutable `StrategyConfig` containing terminal, account, session, strategy, and risk fields.

- [ ] **Step 1: Write failing configuration tests**

```python
from pathlib import Path
import json
import pytest
from gscalp.config import load_config

def test_default_configuration_is_shadow_and_fbs_demo(tmp_path: Path):
    p = tmp_path / "strategy.json"
    p.write_text(json.dumps({
        "terminal_path": r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
        "required_server": "FBS-Demo", "symbol": "XAUUSD",
        "mode": "shadow", "risk_per_trade": 0.0025,
        "daily_loss_limit": 0.005, "max_trades": 2,
        "candidate_sessions_ny": ["08:45-09:45", "09:30-10:30"]
    }))
    cfg = load_config(p)
    assert cfg.mode == "shadow"
    assert cfg.required_server == "FBS-Demo"

def test_live_mode_is_rejected(tmp_path: Path):
    p = tmp_path / "strategy.json"
    p.write_text('{"mode":"live"}')
    with pytest.raises(ValueError, match="live mode is prohibited"):
        load_config(p)
```

- [ ] **Step 2: Run the tests and confirm they fail because `gscalp.config` does not exist**

Run: `python -m pytest tests/test_config.py -v`

Expected: collection error containing `ModuleNotFoundError: No module named 'gscalp'`.

- [ ] **Step 3: Implement package configuration and validation**

Implement frozen dataclasses and reject unknown modes, non-demo servers, risk above 0.25%, daily loss above 0.50%, and max trades above two. The only accepted modes are `read_only`, `shadow`, and `demo`.

- [ ] **Step 4: Add the locked JSON defaults**

```json
{
  "terminal_path": "C:\\Program Files\\FBS MetaTrader 5\\terminal64.exe",
  "required_server": "FBS-Demo",
  "symbol": "XAUUSD",
  "mode": "shadow",
  "risk_per_trade": 0.0025,
  "daily_loss_limit": 0.005,
  "max_trades": 2,
  "candidate_sessions_ny": ["08:45-09:45", "09:30-10:30"],
  "ema_period": 20,
  "atr_period": 14,
  "sweep_atr_min": 0.15,
  "sweep_atr_max": 0.50,
  "displacement_atr_min": 0.50,
  "max_stop_atr": 0.80,
  "minimum_room_r": 1.20,
  "target_r": 1.40
}
```

- [ ] **Step 5: Run configuration tests**

Run: `python -m pytest tests/test_config.py -v`

Expected: all tests pass.

---

### Task 2: Read-Only MT5 Data Gateway

**Files:**
- Create: `src/gscalp/mt5_read.py`
- Create: `src/gscalp/cli.py`
- Test: `tests/test_mt5_read.py`

**Interfaces:**
- Produces: `MT5ReadGateway.connect() -> TerminalSnapshot`
- Produces: `MT5ReadGateway.get_rates(timeframe, start_utc, end_utc) -> pandas.DataFrame`
- Produces: `MT5ReadGateway.get_ticks(start_utc, end_utc) -> pandas.DataFrame`
- Produces: `MT5ReadGateway.get_deals(start_utc, end_utc) -> pandas.DataFrame`
- Never imports or exposes `order_send`.

- [ ] **Step 1: Write adapter tests using a fake MT5 module**

Test that startup rejects a server other than `FBS-Demo`, timestamps are converted to timezone-aware UTC, empty history becomes an empty DataFrame with stable columns, and `shutdown()` executes even after an exception.

- [ ] **Step 2: Run tests and verify the gateway is missing**

Run: `python -m pytest tests/test_mt5_read.py -v`

Expected: import failure for `gscalp.mt5_read`.

- [ ] **Step 3: Implement the read-only gateway**

```python
class MT5ReadGateway:
    def __init__(self, mt5_module, terminal_path: str, required_server: str, symbol: str): ...
    def connect(self): ...
    def get_rates(self, timeframe: int, start_utc, end_utc): ...
    def get_ticks(self, start_utc, end_utc): ...
    def get_deals(self, start_utc, end_utc): ...
    def close(self): ...
```

`connect()` must call `initialize(path=terminal_path)`, verify `terminal_info().connected`, verify `account_info().server`, select the configured symbol, and capture digits, point, tick size/value, contract size, volume minimum/step, stop level, and filling mode.

- [ ] **Step 4: Add a read-only doctor command**

Run: `python -m gscalp.cli doctor`

Expected: JSON containing `server: FBS-Demo`, `symbol: XAUUSD`, `connected: true`, and `can_trade: false` for the application mode even if the account itself permits demo trading.

- [ ] **Step 5: Download research data without modifying the account**

Run: `python -m gscalp.cli download --days 180 --timeframes M1 M5 M15 H1`

Expected: parquet or CSV files under `artifacts/market/`, plus a manifest containing UTC range, row counts, missing-bar gaps, symbol specification, and retrieval timestamp.

---

### Task 3: Deterministic Signal Engine

**Files:**
- Create: `src/gscalp/models.py`
- Create: `src/gscalp/indicators.py`
- Create: `src/gscalp/strategy.py`
- Test: `tests/test_indicators.py`
- Test: `tests/test_strategy.py`

**Interfaces:**
- Produces: `evaluate_bar(context: StrategyContext) -> SignalDecision`
- `SignalDecision` always contains `eligible: bool`, `direction`, `entry`, `stop`, `target`, and ordered reason codes.
- Reason codes include `NEUTRAL_M15`, `NO_LEVEL_SWEEP`, `SWEEP_TOO_SMALL`, `SWEEP_TOO_DEEP`, `NO_RECLAIM`, `WEAK_DISPLACEMENT`, `NO_RETEST`, `STOP_TOO_WIDE`, `INSUFFICIENT_ROOM`, and `QUALIFIED`.

- [ ] **Step 1: Write tests with synthetic completed-bar fixtures**

Create one qualifying long sequence, its mirrored short sequence, and one rejection fixture for every reason code. Add a look-ahead test proving that changing the still-forming next bar cannot change the current decision.

- [ ] **Step 2: Verify all signal tests fail**

Run: `python -m pytest tests/test_indicators.py tests/test_strategy.py -v`

Expected: import failures for the new modules.

- [ ] **Step 3: Implement pure EMA, ATR, swing, and session-level functions**

All functions accept DataFrames and return aligned Series/DataFrames. ATR uses completed true ranges and EMA uses `adjust=False`; calculations must not backfill missing future values.

- [ ] **Step 4: Implement the state machine**

```text
IDLE -> SWEPT -> RECLAIMED -> DISPLACED -> RETESTED -> QUALIFIED
          |          |             |           |
          +----------+-------------+-----------+--> EXPIRED/REJECTED
```

Each transition records bar timestamp, threshold values, actual values, and a reason code. A setup expires after two bars waiting for reclaim or three bars waiting for retest.

- [ ] **Step 5: Run signal tests**

Run: `python -m pytest tests/test_indicators.py tests/test_strategy.py -v`

Expected: all tests pass, including symmetry and no-look-ahead tests.

---

### Task 4: Cost-Aware Backtester and Metrics

**Files:**
- Create: `src/gscalp/backtest.py`
- Create: `src/gscalp/metrics.py`
- Test: `tests/test_backtest.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces: `run_backtest(bars, ticks, config) -> BacktestResult`
- Produces: `summarize(trades) -> MetricsReport`

- [ ] **Step 1: Write execution tests**

Test that longs enter at ask and exit stops at bid, shorts enter at bid and exit stops at ask, a bar touching both stop and target resolves conservatively to the stop unless tick order proves otherwise, positions close at session end, and at most two entries occur.

- [ ] **Step 2: Write metric tests**

For returns `[1.4, -1.0, 1.4, -1.0]`, assert gross expectancy `0.20R`; separately subtract supplied spread/commission costs. Test peak-to-trough drawdown, profit factor, MFE, MAE, consecutive losses, and results grouped by session and regime.

- [ ] **Step 3: Implement the backtester and metrics**

Use M1/tick data for fills and completed M5/M15 bars for decisions. Store entry/exit timestamps, reason trace, spread, commission, slippage assumption, gross R, cost R, net R, MFE, and MAE for every trade.

- [ ] **Step 4: Run all backtester tests**

Run: `python -m pytest tests/test_backtest.py tests/test_metrics.py -v`

Expected: all tests pass.

- [ ] **Step 5: Run the first frozen-parameter research pass**

Run: `python -m gscalp.cli backtest --config config/strategy.json --walk-forward`

Expected artifacts:

```text
artifacts/reports/v0.1-summary.json
artifacts/reports/v0.1-trades.csv
artifacts/reports/v0.1-rejections.csv
artifacts/reports/v0.1-walk-forward.csv
```

Use chronological 60% development, 20% validation, and 20% untouched test partitions. Candidate session selection uses development and validation only; the final selected window is evaluated once on the untouched test set.

---

### Task 5: Shadow-Mode Forward Logger

**Files:**
- Create: `src/gscalp/shadow.py`
- Test: `tests/test_shadow.py`

**Interfaces:**
- Produces: append-only `artifacts/shadow/signals.jsonl`
- Consumes the same `evaluate_bar` function used by the backtester.

- [ ] **Step 1: Write tests proving shadow mode cannot trade**

Inject an MT5 fake whose `order_send` raises immediately and prove a full shadow session never accesses it. Test duplicate-bar suppression, restart recovery, and one decision record per completed M5 bar.

- [ ] **Step 2: Implement the logger**

Every record includes terminal/server identity, UTC and New York timestamps, bar inputs, indicator values, liquidity levels, state transitions, rejection/qualification reasons, hypothetical entry/stop/target, and current spread.

- [ ] **Step 3: Run shadow tests**

Run: `python -m pytest tests/test_shadow.py -v`

Expected: all tests pass.

- [ ] **Step 4: Run at least ten eligible sessions in shadow mode**

Run: `python -m gscalp.cli shadow --config config/strategy.json`

Acceptance gate: zero duplicate signals, zero incomplete-bar decisions, zero attempted orders, and live-computed signals matching an offline replay of the saved bars.

---

### Task 6: Guarded Demo Execution and Recalibration

**Files:**
- Create: `src/gscalp/execution.py`
- Test: `tests/test_execution.py`
- Create: `docs/operations.md`

**Interfaces:**
- Produces: `DemoExecutor.submit(signal, account, symbol_spec, session_state) -> ExecutionResult`
- This is the only module allowed to call `order_check` and `order_send`.

- [ ] **Step 1: Write safety-gate tests**

Reject orders when the server is not `FBS-Demo`, config mode is not `demo`, news data is missing/stale, risk exceeds 0.25%, daily realized plus open risk exceeds 0.50%, trade count is two, spread exceeds the research threshold, session is closed, stop/target are absent, volume violates min/step, or another XAUUSD position exists.

- [ ] **Step 2: Implement broker-aware sizing**

Use MT5 `order_calc_profit` with a 1-lot hypothetical stop to derive loss per lot in account currency, then floor volume to `volume_step`. Recalculate expected loss after rounding and reject rather than exceed the cash-risk cap.

- [ ] **Step 3: Implement preflight and order submission**

Call `order_check` first. Submit one market order with attached SL/TP, a unique magic number, and a versioned comment such as `GSCALP_v0.1_SWEEP`. Persist the request and result before any retry; never retry an ambiguous timeout automatically.

- [ ] **Step 4: Run execution tests with a fake MT5 module**

Run: `python -m pytest tests/test_execution.py -v`

Expected: all tests pass and every unsafe condition produces a stable rejection code.

- [ ] **Step 5: Enable demo execution only after explicit gate review**

Required evidence:

- Positive net expectancy on the untouched historical test partition.
- Profit factor above 1.10 after costs.
- Maximum historical drawdown within the declared risk budget.
- At least ten clean shadow sessions.
- Confirmed daily news-blackout file.
- Manual configuration change from `shadow` to `demo` after reviewing the report.

- [ ] **Step 6: Recalibrate on a fixed cadence**

Review daily for rule compliance, weekly for data/fill anomalies, and only after 40 qualified forward trades for strategy changes. Diagnose in this order: data integrity, broker costs, implementation parity, execution discipline, market regime, then strategy parameters. Change one parameter or filter at a time, repeat the chronological walk-forward test, and record the old/new comparison. Return automatically to shadow mode if rolling 40-trade net expectancy is negative or observed drawdown breaches the historical safety envelope.

---

## Self-Review

- Spec coverage: terminal selection, broker validation, trade-data pulling, exact signal reasons, one-hour constraint, cost-aware evaluation, recalibration, shadow testing, and guarded demo execution are each assigned to a task.
- Safety boundary: Tasks 1–5 cannot place trades; Task 6 is demo-only and gated.
- Type consistency: configuration flows into gateway, strategy, backtester, shadow logger, and executor; the same signal decision object is used throughout.
- No-look-ahead and broker-cost tests are explicit rather than assumed.
- The initial thresholds are frozen hypotheses, preventing post-loss parameter improvisation.

