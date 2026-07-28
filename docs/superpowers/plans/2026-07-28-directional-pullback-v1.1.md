# Directional Pullback Scalper v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a partition-safe, tick-level XAUUSD single-entry directional-pullback research engine that can either reject v1.1 with evidence or lock exactly one historically qualified candidate without submitting an order.

**Architecture:** New `pullback_*` modules preserve the immutable grid v1.0 evidence and separate frozen configuration, completed-bar bias/setup detection, contract-aware sizing, tick-ordered simulation, performance gates, and chronological orchestration. The research pipeline enumerates candidates only in development, opens validation only for development survivors, selects one candidate from validation, and opens test only for that selection; no shadow or demo execution module is part of this plan.

**Tech Stack:** Python 3.11+, pandas, NumPy, DuckDB, MetaTrader5 Python API only for read-only broker calculations, pytest, standard-library `dataclasses`/`enum`/`zoneinfo`, JSON/CSV artifacts, Git/GitHub.

## Global Constraints

- Terminal path is exactly `C:\Program Files\FBS MetaTrader 5\terminal64.exe`.
- Server is exactly `FBS-Demo`; symbol is exactly `XAUUSD`; required MT5 margin mode is retail hedging (`2`).
- Initial application mode is `shadow`, but this plan creates historical research code only.
- Exactly one selected 60-minute New York session is permitted per trading day after historical selection.
- At most one trade attempt and one open v1.1 XAUUSD position are permitted per session.
- No grid, averaging, martingale, recovery entry, opposite hedge, trailing stop, or second attempt is permitted.
- Nominal modeled risk is at most `0.20%`; projected absolute loss including reserve is at most `0.25%` of starting-day equity.
- Projected margin is at most `10%` of free margin.
- Bias and all signals use completed bars only; bias locks at session start.
- Entry is forbidden after minute `45`; any open trade is flattened using the final executable tick before minute `60`.
- Development is `2020-01-02` through `2023-11-29`; validation is `2023-11-30` through `2025-03-24`; test is `2025-03-25` through `2026-07-15`.
- Validation remains unread unless development passes; test remains unread unless validation selects exactly one candidate.
- Validation and test never add or tune candidate values.
- Empty or unrelated news data does not confirm a session; an overlapping high-impact `USD`, `XAU`, `GOLD`, or `ALL` event blocks it.
- A visibly labeled news bypass is exploratory only and can never promote a candidate.
- Existing grid v1.0 modules, configurations, reports, and result documents are not modified.
- Raw `tickstory/*.csv`, canonical `artifacts/`, and generated reports remain untracked.
- Every implementation task follows red-green-refactor and ends with a focused commit.

---

## File Structure

```text
config/pullback-v1.1.json                  frozen safety values and development search space
src/gscalp/pullback_config.py              immutable config, candidate enumeration, JSON loader
src/gscalp/pullback_models.py              directions, reasons, setup/plan/trade/result records
src/gscalp/pullback_bias.py                completed H1/M15 EMA bias logic
src/gscalp/pullback_setup.py               M5 pullback and M1/M5 continuation detection
src/gscalp/pullback_sizing.py              one-position cash-risk and margin sizing
src/gscalp/pullback_backtest.py            tick-ordered entry and exit simulator
src/gscalp/pullback_metrics.py             returns, stresses, concentration, bootstrap, gates
src/gscalp/pullback_pipeline.py            canonical data loading, partition locks, artifacts
src/gscalp/cli.py                          pullback-backtest command only
tests/test_pullback_config.py              frozen contract and model invariants
tests/test_pullback_bias.py                higher-timeframe agreement and no-lookahead
tests/test_pullback_setup.py               pullback, trigger, ATR, spread, and timing rules
tests/test_pullback_sizing.py              broker-aware one-trade sizing
tests/test_pullback_backtest.py            executable sides, causality, exits, one-attempt rule
tests/test_pullback_metrics.py             metric calculations and all research gates
tests/test_pullback_pipeline.py            partition access, candidate selection, artifact integration
tests/test_cli.py                           command delegation and JSON output
docs/research/pullback-v1.1-result.md       committed evidence after the frozen historical run
```

---

### Task 1: Freeze the v1.1 Configuration and Domain Contract

**Files:**
- Create: `config/pullback-v1.1.json`
- Create: `src/gscalp/pullback_config.py`
- Create: `src/gscalp/pullback_models.py`
- Create: `tests/test_pullback_config.py`

**Interfaces:**
- Consumes: `src/gscalp/mt5_read.py::SymbolSpec`.
- Produces: `load_pullback_config(path: Path | str) -> PullbackConfig`.
- Produces: `PullbackConfig.candidates() -> tuple[PullbackCandidate, ...]`.
- Produces: enums `TradeDirection`, `TriggerTimeframe`, `PullbackReason`, and `ExitReason`.
- Produces: frozen records `PullbackCandidate`, `BiasDecision`, `PullbackSetup`, `TradePlan`, `TradeResult`, `SetupDecision`, `PlanDecision`, and `SimulationResult`.

- [ ] **Step 1: Write failing frozen-config tests**

Create `tests/test_pullback_config.py` with a `valid_payload()` containing these exact values:

```python
{
    "version": "pullback-v1.1",
    "terminal_path": r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
    "required_server": "FBS-Demo",
    "symbol": "XAUUSD",
    "mode": "shadow",
    "required_margin_mode": 2,
    "candidate_sessions_ny": ["08:45-09:45", "09:30-10:30", "10:00-11:00"],
    "trigger_timeframes": ["M1", "M5"],
    "target_r_candidates": [0.35, 0.50, 0.65],
    "abort_timeframes": ["M1", "M5"],
    "bias_ema_period": 20,
    "bias_slope_bars": 3,
    "trigger_ema_period": 9,
    "atr_period": 14,
    "trigger_body_fraction_min": 0.35,
    "pullback_atr_min": 0.25,
    "pullback_atr_max": 1.10,
    "stop_buffer_atr": 0.10,
    "stop_buffer_spread_multiple": 2.0,
    "stop_atr_min": 0.35,
    "stop_atr_max": 1.50,
    "reference_spread_minutes": 30,
    "current_spread_multiple": 2.0,
    "nominal_risk_fraction": 0.0020,
    "absolute_risk_fraction": 0.0025,
    "risk_reserve_fraction": 0.0005,
    "max_margin_fraction": 0.10,
    "entry_cutoff_minute": 45,
    "session_minutes": 60,
    "max_trade_attempts_per_session": 1,
    "development_end": "2023-11-29",
    "validation_end": "2025-03-24",
    "test_end": "2026-07-15"
}
```

Add assertions that the loaded dataclass is frozen, creates exactly `3 * 2 * 3 * 2 == 36` unique candidates, and rejects drift in the terminal, server, symbol, mode, margin mode, risk caps, session lengths, one-attempt limit, partition dates, and exact candidate sets.

- [ ] **Step 2: Run the tests and verify the module is absent**

Run:

```powershell
python -m pytest tests/test_pullback_config.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'gscalp.pullback_config'`.

- [ ] **Step 3: Implement the immutable configuration**

In `src/gscalp/pullback_config.py`, define:

```python
@dataclass(frozen=True, slots=True)
class PullbackCandidate:
    session_ny: str
    trigger_timeframe: str
    target_r: float
    abort_timeframe: str

    @property
    def candidate_id(self) -> str:
        session = self.session_ny.replace(":", "").replace("-", "_")
        return f"{session}__{self.trigger_timeframe}__{self.target_r:.2f}R__abort_{self.abort_timeframe}"


@dataclass(frozen=True, slots=True)
class PullbackConfig:
    version: str
    terminal_path: str
    required_server: str
    symbol: str
    mode: str
    required_margin_mode: int
    candidate_sessions_ny: tuple[str, ...]
    trigger_timeframes: tuple[str, ...]
    target_r_candidates: tuple[float, ...]
    abort_timeframes: tuple[str, ...]
    bias_ema_period: int
    bias_slope_bars: int
    trigger_ema_period: int
    atr_period: int
    trigger_body_fraction_min: float
    pullback_atr_min: float
    pullback_atr_max: float
    stop_buffer_atr: float
    stop_buffer_spread_multiple: float
    stop_atr_min: float
    stop_atr_max: float
    reference_spread_minutes: int
    current_spread_multiple: float
    nominal_risk_fraction: float
    absolute_risk_fraction: float
    risk_reserve_fraction: float
    max_margin_fraction: float
    entry_cutoff_minute: int
    session_minutes: int
    max_trade_attempts_per_session: int
    development_end: date
    validation_end: date
    test_end: date

    def candidates(self) -> tuple[PullbackCandidate, ...]:
        return tuple(
            PullbackCandidate(session, trigger, target, abort)
            for session in self.candidate_sessions_ny
            for trigger in self.trigger_timeframes
            for target in self.target_r_candidates
            for abort in self.abort_timeframes
        )
```

Validate exact safety constants, exact candidate tuples, 60-minute windows, positive indicator periods, `risk_reserve_fraction == absolute_risk_fraction - nominal_risk_fraction`, `entry_cutoff_minute == 45`, `session_minutes == 60`, and `max_trade_attempts_per_session == 1`. Reject unknown and missing JSON keys as `grid_config.py` does.

- [ ] **Step 4: Implement reason-coded frozen models**

In `src/gscalp/pullback_models.py`, define exact enums and records:

```python
class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class PullbackReason(str, Enum):
    SETUP_ARMED = "setup_armed"
    NEUTRAL_BIAS = "neutral_bias"
    INSUFFICIENT_BARS = "insufficient_bars"
    INVALID_ATR = "invalid_atr"
    NO_PULLBACK = "no_pullback"
    PULLBACK_TOO_SHALLOW = "pullback_too_shallow"
    PULLBACK_TOO_DEEP = "pullback_too_deep"
    NO_CONTINUATION = "no_continuation"
    TRIGGER_BODY_TOO_SMALL = "trigger_body_too_small"
    TRIGGER_AFTER_CUTOFF = "trigger_after_cutoff"
    SPREAD_TOO_WIDE = "spread_too_wide"
    STOP_TOO_CLOSE = "stop_too_close"
    STOP_TOO_FAR = "stop_too_far"
    BROKER_STOP_INVALID = "broker_stop_invalid"
    VOLUME_BELOW_MINIMUM = "volume_below_minimum"
    RISK_EXCEEDED = "risk_exceeded"
    MARGIN_EXCEEDED = "margin_exceeded"
    NEWS_BLOCKED = "news_blocked"
    EXISTING_EXPOSURE = "existing_exposure"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class ExitReason(str, Enum):
    TARGET_CLOSED = "target_closed"
    STOPPED = "stopped"
    MOMENTUM_ABORT = "momentum_abort"
    SPREAD_ABORT_BEFORE_ENTRY = "spread_abort_before_entry"
    ENTRY_TIMEOUT = "entry_timeout"
    SESSION_FLATTENED = "session_flattened"
```

`BiasDecision` carries direction or `None`, session time, H1/M15 closes, EMA-now values, and EMA-three-bars-ago values. `PullbackSetup` carries candidate, direction, ATR, pullback swing, pre-pullback swing, trigger close time, entry-available time, trigger close, stop, and reference spread. `TradePlan` adds executable entry, target, volume, development spread ceiling, projected loss, projected margin, and starting-day equity. `TradeResult` carries plan, entry/exit timestamps and prices, a trade-closing exit reason, cash PnL, net R, spread paid, and local trading date. `SimulationResult` carries `trade: TradeResult | None` plus an `ExitReason`, allowing spread abort and entry timeout to be recorded without inventing an entry. All timestamps must be timezone-aware; prices, ATR, volume, and equity must be finite and positive where applicable.

- [ ] **Step 5: Write the frozen JSON file and make tests pass**

Create `config/pullback-v1.1.json` with the exact payload from Step 1, then run:

```powershell
python -m pytest tests/test_pullback_config.py -q
```

Expected: all configuration and model tests pass.

- [ ] **Step 6: Commit the contract**

```powershell
git add config/pullback-v1.1.json src/gscalp/pullback_config.py src/gscalp/pullback_models.py tests/test_pullback_config.py
git commit -m "feat: freeze pullback v1.1 contract"
```

---

### Task 2: Calculate Locked Completed-Bar Bias

**Files:**
- Create: `src/gscalp/pullback_bias.py`
- Create: `tests/test_pullback_bias.py`

**Interfaces:**
- Consumes: `PullbackConfig`, `BiasDecision`, `TradeDirection`, UTC-indexed H1/M15 OHLC frames.
- Produces: `completed_before(bars: pd.DataFrame, available_at: pd.Timestamp) -> pd.DataFrame`.
- Produces: `evaluate_locked_bias(h1: pd.DataFrame, m15: pd.DataFrame, session_start: pd.Timestamp, config: PullbackConfig) -> BiasDecision`.

- [ ] **Step 1: Write failing bias tests**

Cover bullish and bearish agreement, H1/M15 disagreement, flat EMA slope, insufficient bars, and a no-lookahead case where changing the incomplete bar at `session_start` cannot change the result:

```python
def test_incomplete_session_start_bar_cannot_change_locked_bias(config, bullish_frames):
    h1, m15 = bullish_frames
    baseline = evaluate_locked_bias(h1, m15, SESSION_START, config)
    mutated = m15.copy()
    mutated.loc[SESSION_START, "close"] = 1_000_000.0

    assert evaluate_locked_bias(h1, mutated, SESSION_START, config) == baseline
    assert baseline.direction is TradeDirection.LONG
```

- [ ] **Step 2: Run tests and observe the expected import failure**

Run:

```powershell
python -m pytest tests/test_pullback_bias.py -q
```

Expected: failure because `gscalp.pullback_bias` does not exist.

- [ ] **Step 3: Implement completed-bar EMA agreement**

Use `bars.index < available_at` for completed inputs. Compute `close.ewm(span=20, adjust=False).mean()` separately on H1 and M15, compare the last close with the last EMA, and compare the last EMA with `EMA.iloc[-4]` for the three-completed-bar slope. Return long only when all four bullish conditions pass, short only when all four bearish conditions pass, otherwise return a neutral decision. Never slice or reference a row at or after `session_start`.

- [ ] **Step 4: Run focused and regression tests**

```powershell
python -m pytest tests/test_pullback_bias.py -q
python -m pytest tests/test_grid_bias.py -q
```

Expected: both suites pass; grid v1.0 behavior remains unchanged.

- [ ] **Step 5: Commit locked bias**

```powershell
git add src/gscalp/pullback_bias.py tests/test_pullback_bias.py
git commit -m "feat: add completed-bar pullback bias"
```

---

### Task 3: Detect Pullbacks and Causal Continuation Triggers

**Files:**
- Create: `src/gscalp/pullback_setup.py`
- Create: `tests/test_pullback_setup.py`

**Interfaces:**
- Consumes: locked `BiasDecision`, one `PullbackCandidate`, completed M1/M5 bars, and pre-session reference spread.
- Produces: `atr(bars: pd.DataFrame, period: int) -> pd.Series`.
- Produces: `detect_pullback_setup(m1: pd.DataFrame, m5: pd.DataFrame, bias: BiasDecision, candidate: PullbackCandidate, session_start: pd.Timestamp, session_end: pd.Timestamp, reference_spread: float, config: PullbackConfig) -> SetupDecision`.
- Produces: either one `PullbackSetup` or one terminal, auditable `PullbackReason`.

- [ ] **Step 1: Write failing ATR and pullback-bound tests**

Build small deterministic OHLC fixtures and assert that ATR uses completed M5 bars before the trigger, a distance below `0.25 ATR` is `PULLBACK_TOO_SHALLOW`, above `1.10 ATR` is `PULLBACK_TOO_DEEP`, and missing/nonpositive ATR is `INVALID_ATR`.

- [ ] **Step 2: Write failing trigger-causality tests**

Test both trigger timeframes and directions. A valid long trigger closes above the prior completed bar high, has `abs(close-open)/(high-low) >= 0.35`, and closes above EMA(9); a short is symmetrical. Assert:

```python
assert decision.setup.trigger_close_time == trigger_bar_open + pd.Timedelta(minutes=1)
assert decision.setup.entry_available_time == decision.setup.trigger_close_time
```

For M5, use five minutes. Mutating any bar whose close time is after `entry_available_time` must not change the decision.

- [ ] **Step 3: Write failing structural stop and timing tests**

For long, require `stop = pullback_low - max(0.10 * atr, 2.0 * reference_spread)`; for short, add the buffer to the pullback high. Reject triggers after minute 45. Entry-price-dependent stop-distance, broker-distance, and current-spread checks belong to Task 4 and Task 5 because the executable entry tick does not exist at completed-bar detection time.

- [ ] **Step 4: Run tests and verify they fail before implementation**

```powershell
python -m pytest tests/test_pullback_setup.py -q
```

Expected: collection or assertion failures for the missing detector.

- [ ] **Step 5: Implement the detector as a completed-bar state scan**

Scan completed M5 bars chronologically inside the session, track the pre-pullback extreme, accept a retracement toward either M5 EMA(20) or the most recent completed breakout/breakdown level, and then scan only the candidate trigger timeframe for the first continuation close. Stop after the first terminal setup decision. Use a half-open session `[session_start, session_end)` and require `entry_available_time <= session_start + 45 minutes`.

Represent the prior breakout level as the most recent completed M5 close beyond the preceding completed M5 high for long, or below the preceding completed M5 low for short. “Toward” is satisfied when the pullback bar range touches the zone between that level and M5 EMA(20).

- [ ] **Step 6: Run detector tests**

```powershell
python -m pytest tests/test_pullback_setup.py -q
```

Expected: all pullback, trigger, structural-stop, cutoff, and no-lookahead tests pass.

- [ ] **Step 7: Commit setup detection**

```powershell
git add src/gscalp/pullback_setup.py tests/test_pullback_setup.py
git commit -m "feat: add causal pullback setup detection"
```

---

### Task 4: Size One Position Within Cash-Risk and Margin Caps

**Files:**
- Create: `src/gscalp/pullback_sizing.py`
- Create: `tests/test_pullback_sizing.py`

**Interfaces:**
- Consumes: `PullbackSetup`, executable entry, `SymbolSpec`, `PullbackConfig`, starting-day equity, free margin, and the existing read-only profit/margin calculator protocol shape.
- Produces: `floor_volume(raw: float, step: float) -> float`.
- Produces: `size_trade(..., trade_id: str) -> PlanDecision`.

- [ ] **Step 1: Write failing sizing tests**

Use a fake calculator and an executable entry price, then assert:

```python
nominal_cash = starting_day_equity * 0.0020
raw_volume = nominal_cash / one_lot_stop_loss
volume = floor_volume(raw_volume, symbol.volume_step)
reserve_cash = starting_day_equity * 0.0005
projected_loss = one_lot_stop_loss * volume + reserve_cash
```

Test flooring rather than rounding, stop distance outside `[0.35 ATR, 1.50 ATR]`, stop closer than `trade_stops_level * point`, below-minimum volume, volume above broker maximum, non-step volume protection, missing/nonpositive loss calculation, projected loss above `0.25%`, invalid/negative margin, and margin above `10%` of free margin.

- [ ] **Step 2: Run tests and verify the expected failure**

```powershell
python -m pytest tests/test_pullback_sizing.py -q
```

Expected: missing-module failure.

- [ ] **Step 3: Implement one-position sizing**

Reuse the read-only `loss_for_one_lot(direction, entry, stop)` and `margin_for_volume(direction, volume, entry)` protocol semantics from `grid_sizing.py`, but calculate a single position. Create target from executable entry:

```python
risk_distance = abs(entry - stop)
target = entry + risk_distance * target_r if direction is LONG else entry - risk_distance * target_r
```

Round stop and target conservatively to `symbol.tick_size`, recalculate loss after rounding, add reserve cash, and reject rather than clamp whenever any broker or safety invariant fails.

- [ ] **Step 4: Run sizing and grid-regression tests**

```powershell
python -m pytest tests/test_pullback_sizing.py tests/test_grid_sizing.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit sizing**

```powershell
git add src/gscalp/pullback_sizing.py tests/test_pullback_sizing.py
git commit -m "feat: add capped pullback trade sizing"
```

---

### Task 5: Simulate One Trade with Tick-Ordered Execution

**Files:**
- Create: `src/gscalp/pullback_backtest.py`
- Create: `tests/test_pullback_backtest.py`

**Interfaces:**
- Consumes: a `TradePlan`, UTC bid/ask ticks, completed abort-timeframe bars, session end, contract size, and optional spread stress.
- Produces: `CostStress(spread_multiplier: float = 1.0, additional_r_cost: float = 0.0)`.
- Produces: `simulate_trade(plan: TradePlan, ticks: pd.DataFrame, abort_bars: pd.DataFrame, session_end: pd.Timestamp, contract_size: float, stress: CostStress = CostStress()) -> SimulationResult`.

- [ ] **Step 1: Write failing executable-side tests**

Assert that `SimulationResult.trade` for a long enters at the first ask after `entry_available_time` and exits on bid, while a short enters at bid and exits on ask. Ticks exactly before the trigger close are ineligible. Verify cash PnL uses `price_delta * volume * contract_size` and net R divides by the planned non-reserve stop loss.

- [ ] **Step 2: Write failing conservative-order tests**

Cover target, stop, same-tick target/stop ambiguity resolving to `STOPPED`, spread abort before entry, entry timeout at minute 45, and session flatten using the last executable tick strictly before minute 60.

- [ ] **Step 3: Write failing momentum-abort tests**

Build M1 and M5 completed-bar fixtures where the close crosses EMA(9) against the position. The abort becomes executable only on the first later tick. If executable price reached target before the abort decision became available, target wins; otherwise the abort closes at the correct bid/ask side.

- [ ] **Step 4: Write failing one-attempt invariants**

Assert `simulate_trade` creates exactly zero or one entry, never re-enters after any exit, rejects non-UTC indexes, rejects unsorted or duplicate ticks, and conservatively uses the original fixed stop and target for the entire trade.

- [ ] **Step 5: Run tests and verify failure**

```powershell
python -m pytest tests/test_pullback_backtest.py -q
```

Expected: failures because the simulator is absent.

- [ ] **Step 6: Implement the event-ordered simulator**

Validate and sort nothing silently: inputs must already be monotonic, unique, UTC-aware, and have nonnegative spread. Iterate ticks once; on each tick process an existing stop before target, then any completed-bar momentum abort that has become available, then session flatten. Before entry, enforce the setup availability time, minute-45 cutoff, and:

```python
current_spread <= min(plan.development_spread_ceiling, plan.setup.reference_spread * 2.0)
```

Apply stress by widening ask away from bid while never improving an executable price.

- [ ] **Step 7: Run simulator tests**

```powershell
python -m pytest tests/test_pullback_backtest.py -q
```

Expected: all causal execution, exit precedence, and one-attempt tests pass.

- [ ] **Step 8: Commit the simulator**

```powershell
git add src/gscalp/pullback_backtest.py tests/test_pullback_backtest.py
git commit -m "feat: add tick-level pullback simulator"
```

---

### Task 6: Calculate Metrics, Stress Results, and Frozen Gates

**Files:**
- Create: `src/gscalp/pullback_metrics.py`
- Create: `tests/test_pullback_metrics.py`

**Interfaces:**
- Consumes: chronological `TradeResult` sequences.
- Produces: frozen `PullbackMetrics`.
- Produces: `summarize_trades(trades: Iterable[TradeResult]) -> PullbackMetrics`.
- Produces: `bootstrap_expectancy_lower_bound(net_r: Sequence[float], *, seed: int = 1101, samples: int = 10_000, confidence: float = 0.90) -> float`.
- Produces: `development_gate(base, spread_stress, cost_stress, bootstrap_lower) -> bool`.
- Produces: `validation_gate(base, spread_stress) -> bool`.
- Produces: `test_gate(base, spread_stress, bootstrap_lower) -> bool`.
- Produces: `validation_score(metrics: PullbackMetrics) -> float`.

- [ ] **Step 1: Write failing metric-calculation tests**

Assert exact trade count, win rate, net expectancy, sample standard deviation, standard error, profit factor, cumulative-R maximum drawdown, minimum individual R, and calendar-year trade concentration. Define profit factor as gross positive R divided by absolute gross negative R, returning positive infinity when there are gains and no losses, and zero when there are no gains.

- [ ] **Step 2: Write failing deterministic-bootstrap tests**

Use NumPy `default_rng(seed)` and resample whole trade R values with replacement. Assert identical input/seed produces identical 10th-percentile mean and empty input returns negative infinity.

- [ ] **Step 3: Write one failing test per gate boundary**

Development must enforce: `trade_count >= 100`, expectancy `> 0`, profit factor `> 1.15`, 1.25x-spread expectancy `> 0`, additional-0.05R expectancy `> 0`, drawdown `<= 8R`, maximum year share `<= 0.35`, stressed minimum trade `>= -1.10R`, and bootstrap lower `>= -0.05R`.

Validation must enforce: `trade_count >= 30`, expectancy `> 0`, profit factor `> 1.10`, 1.25x-spread expectancy `> 0`, drawdown `<= 8R`, and stressed minimum trade `>= -1.10R`.

Test must enforce: `trade_count >= 20`, expectancy `> 0`, profit factor `> 1.10`, 1.25x-spread expectancy `> 0`, drawdown `<= 8R`, and bootstrap lower `>= -0.05R`.

- [ ] **Step 4: Write the validation-selection test**

Assert candidates are ranked only by:

```python
validation_score = spread_stressed_expectancy - spread_stressed_standard_error
```

Break exact ties lexicographically by `candidate_id`, never by any test metric.

- [ ] **Step 5: Run tests and verify failure**

```powershell
python -m pytest tests/test_pullback_metrics.py -q
```

Expected: missing-module failure.

- [ ] **Step 6: Implement metrics and gates**

Keep every threshold as a named constant in `pullback_metrics.py`. Return a metrics record for an empty sequence instead of raising, using zero counts and conservative nonpassing sentinel values. Sort by entry timestamp before equity-curve and year-concentration calculations.

- [ ] **Step 7: Run metric and grid-regression suites**

```powershell
python -m pytest tests/test_pullback_metrics.py tests/test_grid_metrics.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit metrics**

```powershell
git add src/gscalp/pullback_metrics.py tests/test_pullback_metrics.py
git commit -m "feat: add pullback research gates"
```

---

### Task 7: Orchestrate Partition-Safe Research and Canonical Data Loading

**Files:**
- Create: `src/gscalp/pullback_pipeline.py`
- Create: `tests/test_pullback_pipeline.py`

**Interfaces:**
- Consumes: frozen config, canonical Tickstory parquet root, strict `grid_news.news_gate`, component functions from Tasks 2–6, and read-only `SymbolSpec`.
- Produces: `CandidateEvaluation`, `PartitionEvaluation`, and `PullbackResearchSummary`.
- Produces protocol `PartitionSource.load_development()`, `load_validation(candidate_ids)`, and `load_test(candidate_id)`.
- Produces: `ParquetPullbackSource(config, market_root, news_path=Path("data/news_blackouts.csv"))`.
- Produces: `run_pullback_research(config_path, market_root, output_dir, *, news_path=Path("data/news_blackouts.csv"), source=None) -> PullbackResearchSummary`.

- [ ] **Step 1: Write failing partition-access tests with a spy source**

Test these exact flows:

```text
development fails -> validation calls 0, test calls 0, status development_rejected
development passes -> validation receives only passing candidate IDs
validation fails -> test calls 0, status validation_rejected
validation passes -> test receives exactly selected candidate ID
test fails -> status test_rejected
test passes -> status historical_passed, selected_candidate populated
```

Assert no summary field reads validation or test data before its gate.

- [ ] **Step 2: Write failing selection and spread-freeze tests**

Development calculates and records one spread ceiling per session window as the NumPy `0.90` quantile of every nonnegative bid/ask spread observed between minutes 0 and 45 across that window’s development sessions. All trigger/target/abort variants for the same window share that ceiling. Validation and test receive and reuse the exact stored development value. Validation selects by stressed expectancy minus standard error with deterministic ID tie-breaking. Test results never affect selection.

- [ ] **Step 3: Write failing strict-news tests**

Use temporary CSVs to assert missing files, header-only files, unrelated same-date events, and noncovering `NO_HIGH_IMPACT_EVENTS` rows become `NEWS_BLOCKED` rejection rows. Assert overlapping high-impact `USD`, `XAU`, `GOLD`, and `ALL` rows block. Assert a bypass source string containing `BYPASS` marks `promotion_eligible=False` in the summary even if every performance gate passes.

- [ ] **Step 4: Write failing canonical-loader tests**

Build temporary DuckDB parquet fixtures with:

```text
market/manifest.json
market/bars/M1.parquet
market/bars/M5.parquet
market/bars/M15.parquet
market/bars/H1.parquet
market/ticks/year=2020/ticks.parquet
```

Assert the source reads only development year/date ranges until asked for later partitions, converts canonical `Timestamp/BidOpen/BidHigh/BidLow/BidClose` columns into UTC-indexed lowercase OHLC frames, keeps bid/ask ticks, hashes the manifest, and never initializes MT5.

- [ ] **Step 5: Write failing session-evaluation integration tests**

For each local trading date/candidate:

1. Convert the New York session to UTC with `zoneinfo.ZoneInfo("America/New_York")`.
2. Apply the strict news gate.
3. Compute reference spread from ticks in the 30 minutes before session start.
4. Lock H1/M15 bias at session start.
5. Detect at most one setup.
6. Use the first eligible tick as executable entry for sizing.
7. Simulate at most one trade.
8. Record `SimulationResult.trade` as one trade row, or record its no-entry reason as one rejection row.

Assert DST dates convert correctly and a future bar/tick beyond the decision boundary cannot alter an earlier decision.

- [ ] **Step 6: Run pipeline tests and verify failure**

```powershell
python -m pytest tests/test_pullback_pipeline.py -q
```

Expected: failures because orchestration is absent.

- [ ] **Step 7: Implement partition orchestration**

Enumerate all 36 candidates in development. Evaluate base, 1.25x spread, and additional 0.05R cost stress from the same planned trades. Open validation only for development-gate survivors; select exactly one validation-gate survivor; open test only for that ID. Return explicit booleans `development_accessed`, `validation_accessed`, `test_accessed`, `promotion_eligible`, and a status from:

```text
development_rejected
validation_rejected
test_rejected
historical_passed
```

Do not import `MetaTrader5` or any order interface in this module.

- [ ] **Step 8: Implement atomic versioned artifacts**

Write UTF-8 temporary files and replace final paths only after a successful write:

```text
pullback-v1.1-development.csv
pullback-v1.1-validation.csv
pullback-v1.1-test.csv
pullback-v1.1-trades.csv
pullback-v1.1-rejections.csv
pullback-v1.1-stress.csv
pullback-v1.1-summary.json
```

The summary must include config SHA-256, manifest SHA-256, news-file SHA-256, candidate counts, selected candidate, partition-access flags, promotion eligibility, metrics/gates, reason counts, and paths. Emit strict JSON with no `NaN` or `Infinity`; encode unavailable finite metrics as `null`.

- [ ] **Step 9: Run pipeline and full regression tests**

```powershell
python -m pytest tests/test_pullback_pipeline.py -q
python -m pytest -q
```

Expected: all new and existing tests pass.

- [ ] **Step 10: Commit the pipeline**

```powershell
git add src/gscalp/pullback_pipeline.py tests/test_pullback_pipeline.py
git commit -m "feat: add partition-safe pullback research"
```

---

### Task 8: Add the Historical-Research CLI Boundary

**Files:**
- Modify: `src/gscalp/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_pullback_research`.
- Produces: `gscalp pullback-backtest --config ... --market-root ... --news ... --output ...`.
- Does not produce: shadow, demo, order-check, order-send, or automatic promotion commands.

- [ ] **Step 1: Write the failing CLI delegation test**

Append a test that injects `pullback_runner` into `main`, invokes:

```powershell
gscalp pullback-backtest --config config/pullback-v1.1.json --market-root artifacts/market --news data/news_blackouts.csv --output artifacts/reports
```

Assert the runner receives four `Path` arguments in order and stdout is the summary’s JSON-safe dictionary.

- [ ] **Step 2: Run the focused test and verify failure**

```powershell
python -m pytest tests/test_cli.py::test_pullback_backtest_command_delegates_to_partition_safe_runner -q
```

Expected: failure because `pullback-backtest` is not registered.

- [ ] **Step 3: Register the read-only command**

Add parser arguments `--config`, `--market-root`, `--news`, and `--output`; default to the frozen config, canonical market root, strict news CSV, and report directory. Add `pullback_runner=run_pullback_research` injection to `main` and return exit code `0` for completed research regardless of pass/reject status; input/contract errors remain nonzero exceptions handled by the existing CLI boundary.

- [ ] **Step 4: Verify the CLI and static trading-interface absence**

```powershell
python -m pytest tests/test_cli.py -q
rg -n "order_send|order_check|TRADE_ACTION|ORDER_TYPE_BUY|ORDER_TYPE_SELL" src/gscalp/pullback_*.py
```

Expected: CLI tests pass and `rg` returns no matches. Read-only profit/margin calculations are accessed through the injected calculator protocol, not order submission constants.

- [ ] **Step 5: Commit the command**

```powershell
git add src/gscalp/cli.py tests/test_cli.py
git commit -m "feat: add pullback research command"
```

---

### Task 9: Execute the Frozen Historical Run and Record the Decision

**Files:**
- Create: `docs/research/pullback-v1.1-result.md`
- Generated and ignored: `artifacts/reports/pullback-v1.1-*.csv`
- Generated and ignored: `artifacts/reports/pullback-v1.1-summary.json`

**Interfaces:**
- Consumes: canonical Tickstory market data through `2026-07-15`, frozen config, and `data/news_blackouts.csv`.
- Produces: a committed evidence document that either retires v1.1 or identifies the single historically qualified candidate.

- [ ] **Step 1: Verify repository and data preconditions**

Run:

```powershell
git status --short
python -m pytest -q
Get-Content data/news_blackouts.csv -TotalCount 5
```

Expected: clean code state, all tests pass, and the news file has the required header. Session-by-session coverage for all three windows is audited by the pullback pipeline itself; promotion is impossible unless every evaluated session has either a covering source-backed `NO_HIGH_IMPACT_EVENTS` row or an applicable high-impact blackout decision.

- [ ] **Step 2: Run the source-backed frozen research**

```powershell
python -m gscalp.cli pullback-backtest --config config/pullback-v1.1.json --market-root "D:\Source Codes\Codex\GSCALP\artifacts\market" --news data/news_blackouts.csv --output artifacts/reports
```

Expected: seven versioned artifacts are produced. If news coverage is incomplete, the result is a nonpromotable `development_rejected` report with auditable `news_blocked` reasons; do not infer “no news.”

- [ ] **Step 3: If needed, run one explicitly nonpromotable news-bypass diagnostic**

Only when the source-backed run is blocked by missing historical confirmations, use an ignored CSV whose source contains `USER_APPROVED_NEWS_BYPASS_NOT_SOURCE_BACKED`, rerun into `artifacts/reports-news-bypass`, and confirm:

```python
summary.promotion_eligible is False
```

This diagnostic can measure raw strategy behavior but cannot select a shadow/demo configuration.

- [ ] **Step 4: Audit partition safety and result integrity**

Inspect `pullback-v1.1-summary.json` and assert:

```text
development failure -> validation_accessed false and test_accessed false
validation failure -> test_accessed false
historical_passed -> selected_candidate is non-null and promotion_eligible true
news bypass -> promotion_eligible false
```

Recalculate trade count, expectancy, profit factor, maximum drawdown, worst stressed trade, and year concentration independently from the emitted trade/stress CSVs and reconcile them to the summary.

- [ ] **Step 5: Write the evidence document**

Create `docs/research/pullback-v1.1-result.md` with:

```markdown
# Pullback v1.1 Historical Result

**Decision:** RETIRED or HISTORICAL GATE PASSED — SHADOW STILL DISABLED
**Run date:** 28 July 2026
**Config SHA-256:** Copy the exact `config_sha256` string from the summary.
**Market manifest SHA-256:** Copy the exact `data_manifest_sha256` string from the summary.
**News SHA-256:** Copy the exact `news_sha256` string from the summary.

## Partition Access

Record development, validation, and test access exactly as reported.

## Candidate Evidence

Report base and stressed count, expectancy, profit factor, maximum drawdown,
bootstrap lower bound, year concentration, and gate result for every partition
that was legitimately accessed.

## Rejections

Report every reason count and distinguish source-backed news rejection from an
explicit exploratory bypass.

## Decision

If any required gate failed, retire v1.1 without using validation/test to tune
it. If all gates passed, record the one selected candidate but state that order
submission remains disabled pending a separately approved shadow implementation.
```

Replace the explanatory SHA-256 sentences and decision alternatives with the exact emitted values before committing the result document.

- [ ] **Step 6: Run final verification**

```powershell
python -m pytest -q
rg -n "order_send|order_check|TRADE_ACTION" src/gscalp/pullback_*.py
git status --short
```

Expected: all tests pass, the trading-interface scan has no matches, only the intended result document/code changes are tracked, and large data/report artifacts remain ignored.

- [ ] **Step 7: Commit and push the evidence**

```powershell
git add docs/research/pullback-v1.1-result.md
git commit -m "docs: record pullback v1.1 historical result"
git push origin feat/grid-v1-research
```

Expected: the draft PR contains the reproducible code and evidence document, but no generated market data and no shadow/demo executor.

---

## Historical Completion Boundary

This plan is complete only when the frozen v1.1 code is tested, its source-backed or explicitly nonpromotable diagnostic run is reproducible, and `docs/research/pullback-v1.1-result.md` states a defensible retire/pass decision.

Even a historical pass does not complete the wider trading-system goal. It authorizes a separate reviewed specification and implementation plan for ten no-trade shadow sessions, offline/live parity checks, and only then user-approved FBS demo execution. It never authorizes real-money trading.
