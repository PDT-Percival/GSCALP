# Directional Grid Research Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and historically validate a reason-coded, three-level XAUUSD directional-grid research engine that risks no more than 0.25% per one-hour basket.

**Architecture:** New `grid_*` modules preserve the immutable v0.x implementation while separating locked bias, structural geometry, broker-aware sizing, tick-ordered fills, metrics, and chronological orchestration. The pipeline may open validation only after a development gate passes and may open the test tail only after one validation window is locked.

**Tech Stack:** Python 3.14, pandas, NumPy, DuckDB, MetaTrader5 Python API for read-only broker specifications and sizing parity, pytest, standard-library `zoneinfo`, JSON/CSV artifacts, Git/GitHub.

## Global Constraints

- Terminal path is exactly `C:\Program Files\FBS MetaTrader 5\terminal64.exe`.
- Server is exactly `FBS-Demo`; symbol is exactly `XAUUSD`.
- Research and shadow code have no order-submission interface.
- Account execution mode must be MT5 retail hedging; another margin mode is a hard rejection.
- One declared New York-time window is exactly 60 minutes.
- One basket per session; three same-direction levels; equal level volume.
- Nominal basket risk is at most 0.20% of starting-day equity.
- Absolute stressed basket risk is at most 0.25% of starting-day equity.
- No martingale, opposite hedge, fourth level, recentering, stop widening, or recovery order.
- Pending levels expire at minute 45; positions flatten by minute 60.
- Development ends 2023-11-29, validation ends 2025-03-24, and test ends 2026-07-15.
- Validation remains unread unless development passes. Test remains unread unless validation locks one window.
- Raw `tickstory/*.csv` and generated `artifacts/` remain untracked.
- Every code task follows red-green-refactor and ends with a focused commit.

---

## File Structure

```text
config/grid-v1.0.json                     frozen v1.0 research values
src/gscalp/grid_config.py                 immutable config and JSON loader
src/gscalp/grid_models.py                 bias, geometry, plan, leg, basket, reasons
src/gscalp/grid_bias.py                   completed-bar bias and confirmed pivots
src/gscalp/grid_geometry.py               anchor/stop/levels/target and price rounding
src/gscalp/grid_sizing.py                 worst-case cash loss and margin sizing
src/gscalp/grid_backtest.py               tick-ordered pending-order/basket simulator
src/gscalp/grid_metrics.py                summaries, stresses, bootstrap, gates
src/gscalp/grid_pipeline.py               partition-safe orchestration and artifacts
tests/test_grid_config.py                 config invariants
tests/test_grid_bias.py                   bias/pivot/no-lookahead
tests/test_grid_geometry.py               geometry and rejection codes
tests/test_grid_sizing.py                 broker-aware basket sizing
tests/test_grid_backtest.py               fills, targets, stops, expiry, flatten
tests/test_grid_metrics.py                costs, drawdown, confidence, gates
tests/test_grid_pipeline.py               partition access and artifact integration
docs/research/grid-v1.0-result.md          committed evidence summary
```

---

### Task 1: Establish Repository Baseline and Immutable Grid Contract

**Files:**
- Modify: `.gitignore`
- Modify: `pyproject.toml`
- Create: `config/grid-v1.0.json`
- Create: `src/gscalp/grid_config.py`
- Create: `src/gscalp/grid_models.py`
- Create: `tests/test_grid_config.py`

**Interfaces:**
- Consumes: existing Python package layout and `src/gscalp/mt5_read.py::SymbolSpec`.
- Produces: `load_grid_config(path: Path | str) -> GridConfig`.
- Produces: `BiasDirection`, `GridReason`, `BiasDecision`, `GridGeometry`, `GridLevelPlan`, `GridPlan`, `LegResult`, and `BasketResult`.

- [ ] **Step 1: Initialize the empty remote without overwriting local files**

Run:

```powershell
git init -b main
git remote add origin https://github.com/PDT-Percival/GSCALP.git
git ls-remote origin
git status --short
```

Expected: `git ls-remote origin` returns no refs; all current files are untracked; no file content changes.

- [ ] **Step 2: Strengthen generated-data exclusions**

Append these exact exclusions to `.gitignore`:

```gitignore
artifacts/
tickstory/*.csv
*.parquet
*.jsonl
.openai/
```

Run:

```powershell
git check-ignore artifacts/market/bars/M5.parquet tickstory/XAUUSD_ticks_2020.csv
```

Expected: both large data paths are ignored.

- [ ] **Step 3: Write failing configuration tests**

Create `tests/test_grid_config.py` with:

```python
import json
from dataclasses import FrozenInstanceError

import pytest

from gscalp.grid_config import load_grid_config


def valid_grid_payload():
    return {
        "version": "grid-v1.0",
        "terminal_path": r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
        "required_server": "FBS-Demo",
        "symbol": "XAUUSD",
        "mode": "shadow",
        "required_margin_mode": 2,
        "candidate_sessions_ny": ["08:45-09:45", "09:30-10:30"],
        "ema_period": 20,
        "atr_period": 14,
        "pivot_left": 2,
        "pivot_right": 2,
        "pivot_lookback": 12,
        "stop_buffer_atr": 0.10,
        "stop_buffer_spread_multiple": 2.0,
        "invalidation_atr_min": 0.60,
        "invalidation_atr_max": 1.50,
        "level_fractions": [0.25, 0.50, 0.75],
        "profit_distance_fraction": 0.25,
        "reference_spread_multiple": 4.0,
        "current_spread_multiple": 2.0,
        "profit_distance_max_fraction": 0.40,
        "nominal_risk_fraction": 0.0020,
        "absolute_risk_fraction": 0.0025,
        "max_margin_fraction": 0.10,
        "pending_expiry_minute": 45,
        "session_minutes": 60,
        "max_baskets_per_session": 1,
        "development_end": "2023-11-29",
        "validation_end": "2025-03-24",
        "test_end": "2026-07-15",
    }


def test_grid_config_is_frozen_and_exactly_demo_scoped(tmp_path):
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(valid_grid_payload()))
    config = load_grid_config(path)
    assert config.level_fractions == (0.25, 0.50, 0.75)
    assert config.nominal_risk_fraction == 0.002
    assert config.absolute_risk_fraction == 0.0025
    with pytest.raises(FrozenInstanceError):
        config.mode = "demo"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_server", "FBS-Real"),
        ("nominal_risk_fraction", 0.0021),
        ("absolute_risk_fraction", 0.0026),
        ("max_baskets_per_session", 2),
        ("level_fractions", [0.25, 0.50, 0.80]),
        ("pending_expiry_minute", 46),
        ("session_minutes", 59),
    ],
)
def test_grid_config_rejects_safety_drift(tmp_path, field, value):
    payload = valid_grid_payload()
    payload[field] = value
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_grid_config(path)
```

- [ ] **Step 4: Run tests and observe the missing module**

Run:

```powershell
python -m pytest tests/test_grid_config.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'gscalp.grid_config'`.

- [ ] **Step 5: Implement the immutable configuration**

Create `src/gscalp/grid_config.py` around this exact public contract:

```python
@dataclass(frozen=True, slots=True)
class GridConfig:
    version: str
    terminal_path: str
    required_server: str
    symbol: str
    mode: str
    required_margin_mode: int
    candidate_sessions_ny: tuple[str, ...]
    ema_period: int
    atr_period: int
    pivot_left: int
    pivot_right: int
    pivot_lookback: int
    stop_buffer_atr: float
    stop_buffer_spread_multiple: float
    invalidation_atr_min: float
    invalidation_atr_max: float
    level_fractions: tuple[float, float, float]
    profit_distance_fraction: float
    reference_spread_multiple: float
    current_spread_multiple: float
    profit_distance_max_fraction: float
    nominal_risk_fraction: float
    absolute_risk_fraction: float
    max_margin_fraction: float
    pending_expiry_minute: int
    session_minutes: int
    max_baskets_per_session: int
    development_end: date
    validation_end: date
    test_end: date


def load_grid_config(path: Path | str) -> GridConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    raw["candidate_sessions_ny"] = tuple(raw["candidate_sessions_ny"])
    raw["level_fractions"] = tuple(raw["level_fractions"])
    for field_name in ("development_end", "validation_end", "test_end"):
        raw[field_name] = date.fromisoformat(raw[field_name])
    return GridConfig(**raw)
```

Validation must require the exact version, terminal, server, symbol, shadow/read-only/demo modes only, margin mode `2`, three sorted fractions exactly `(0.25, 0.50, 0.75)`, risk ceilings, minute 45/60, one basket, two 60-minute candidate sessions, and ordered partition dates.

- [ ] **Step 6: Add the frozen JSON**

Create `config/grid-v1.0.json` with the exact payload returned by `valid_grid_payload()`. Do not add optimization ranges to this file.

- [ ] **Step 7: Define reason-coded immutable models**

Create `src/gscalp/grid_models.py` with these public names:

```python
class BiasDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class GridReason(str, Enum):
    BIAS_LOCKED = "bias_locked"
    NEUTRAL_BIAS = "neutral_bias"
    ATR_UNAVAILABLE = "atr_unavailable"
    NO_CONFIRMED_PIVOT = "no_confirmed_pivot"
    INVALIDATION_TOO_CLOSE = "invalidation_too_close"
    INVALIDATION_TOO_FAR = "invalidation_too_far"
    SPREAD_TOO_WIDE = "spread_too_wide"
    NEWS_BLOCKED = "news_blocked"
    BROKER_DISTANCE_INVALID = "broker_distance_invalid"
    VOLUME_BELOW_MINIMUM = "volume_below_minimum"
    BASKET_RISK_EXCEEDED = "basket_risk_exceeded"
    MARGIN_LIMIT_EXCEEDED = "margin_limit_exceeded"
    EXISTING_EXPOSURE = "existing_exposure"
    GRID_ARMED = "grid_armed"
    LEVEL_1_FILLED = "level_1_filled"
    LEVEL_2_FILLED = "level_2_filled"
    LEVEL_3_FILLED = "level_3_filled"
    BIAS_ABORT = "bias_abort"
    TARGET_CLOSED = "target_closed"
    STOPPED = "stopped"
    PENDING_EXPIRED = "pending_expired"
    SESSION_FLATTENED = "session_flattened"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True, slots=True)
class BiasDecision:
    direction: BiasDirection | None
    reason: GridReason
    as_of: pd.Timestamp
    ema_now: float | None
    ema_three_bars_ago: float | None


@dataclass(frozen=True, slots=True)
class GridGeometry:
    direction: BiasDirection
    session_start: pd.Timestamp
    session_end: pd.Timestamp
    anchor: float
    stop: float
    atr: float
    reference_spread: float
    current_spread: float
    profit_distance: float
    level_prices: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class GridLevelPlan:
    level_number: int
    requested_price: float
    volume: float
    stop: float
    provisional_target: float


@dataclass(frozen=True, slots=True)
class GridPlan:
    basket_id: str
    geometry: GridGeometry
    levels: tuple[GridLevelPlan, GridLevelPlan, GridLevelPlan]
    projected_loss_cash: float
    projected_margin_cash: float


@dataclass(frozen=True, slots=True)
class LegResult:
    level_number: int
    fill_time: pd.Timestamp
    fill_price: float
    exit_time: pd.Timestamp
    exit_price: float
    volume: float
    reason: GridReason
    pnl_cash: float


@dataclass(frozen=True, slots=True)
class BasketResult:
    basket_id: str
    direction: BiasDirection
    session_start: pd.Timestamp
    exit_time: pd.Timestamp
    reason: GridReason
    legs: tuple[LegResult, ...]
    gross_r: float
    cost_r: float
    net_r: float
    mfe_r: float
    mae_r: float
    maximum_levels_filled: int
```

All timestamps must be timezone-aware and all level tuples must contain exactly three monotonically ordered values.

- [ ] **Step 8: Run configuration tests**

Run:

```powershell
python -m pytest tests/test_grid_config.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit the baseline**

Run:

```powershell
git add .gitignore pyproject.toml config data docs src tests
git commit -m "chore: establish GSCALP research baseline"
git push -u origin main
```

Expected: source, tests, design, and plans are on `origin/main`; raw ticks, parquet files, reports, and journals are absent from the commit.

---

### Task 2: Locked Bias and Confirmed Structural Pivot

**Files:**
- Create: `src/gscalp/grid_bias.py`
- Create: `tests/test_grid_bias.py`

**Interfaces:**
- Consumes: `GridConfig`, canonical M15/M5 OHLC frames, timezone-aware `as_of`.
- Produces: `evaluate_locked_bias(m15, as_of, config) -> BiasDecision`.
- Produces: `confirmed_pivot(m5, as_of, direction, config) -> tuple[pd.Timestamp, float] | None`.

- [ ] **Step 1: Write failing bias and no-lookahead tests**

Create `tests/test_grid_bias.py`:

```python
from dataclasses import replace

import pandas as pd

from gscalp.grid_bias import confirmed_pivot, evaluate_locked_bias
from gscalp.grid_models import BiasDirection, GridReason


def test_bullish_bias_uses_only_completed_m15_bars(grid_config, bullish_m15):
    as_of = bullish_m15.index[-1] + pd.Timedelta(minutes=15)
    expected = evaluate_locked_bias(bullish_m15, as_of, grid_config)
    future = bullish_m15.copy()
    future.loc[as_of] = {"open": 1, "high": 10_000, "low": 0, "close": 1}
    actual = evaluate_locked_bias(future, as_of, grid_config)
    assert expected == actual
    assert actual.direction is BiasDirection.LONG
    assert actual.reason is GridReason.BIAS_LOCKED


def test_neutral_bias_when_structure_disagrees(grid_config, bullish_m15):
    broken = bullish_m15.copy()
    broken.iloc[-1, broken.columns.get_loc("low")] = broken.iloc[-2]["low"] - 1
    result = evaluate_locked_bias(
        broken, broken.index[-1] + pd.Timedelta(minutes=15), grid_config
    )
    assert result.direction is None
    assert result.reason is GridReason.NEUTRAL_BIAS


def test_pivot_requires_two_completed_bars_on_the_right(grid_config, pivot_m5):
    as_of = pivot_m5.index[-1] + pd.Timedelta(minutes=5)
    pivot = confirmed_pivot(pivot_m5, as_of, BiasDirection.LONG, grid_config)
    assert pivot == (pivot_m5.index[-3], pivot_m5.iloc[-3]["low"])
    changed_future = pivot_m5.copy()
    changed_future.loc[as_of] = {"open": 0, "high": 1, "low": -999, "close": 0}
    assert confirmed_pivot(
        changed_future, as_of, BiasDirection.LONG, grid_config
    ) == pivot
```

Add shared fixtures to `tests/conftest.py` only when they are used by at least two grid test modules; otherwise keep fixtures local.

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
python -m pytest tests/test_grid_bias.py -v
```

Expected: import failure for `gscalp.grid_bias`.

- [ ] **Step 3: Implement completed-bar helpers**

Create `src/gscalp/grid_bias.py` with:

```python
def completed_bars(
    bars: pd.DataFrame, as_of: pd.Timestamp, timeframe_minutes: int
) -> pd.DataFrame:
    if bars.index.tz is None or as_of.tzinfo is None:
        raise ValueError("bars and as_of must be timezone-aware")
    utc = bars.copy()
    utc.index = utc.index.tz_convert("UTC")
    cutoff = as_of.tz_convert("UTC")
    return utc.loc[
        utc.index + pd.Timedelta(minutes=timeframe_minutes) <= cutoff
    ]


def evaluate_locked_bias(
    m15: pd.DataFrame, as_of: pd.Timestamp, config: GridConfig
) -> BiasDecision:
    bars = completed_bars(m15, as_of, 15)
    average = ema(bars["close"], config.ema_period)
    if len(bars) < config.ema_period + 3 or pd.isna(average.iloc[-1]):
        return BiasDecision(None, GridReason.NEUTRAL_BIAS, as_of, None, None)
    latest, previous = bars.iloc[-1], bars.iloc[-2]
    bullish = (
        latest["close"] > average.iloc[-1]
        and average.iloc[-1] > average.iloc[-4]
        and latest["high"] > previous["high"]
        and latest["low"] > previous["low"]
    )
    bearish = (
        latest["close"] < average.iloc[-1]
        and average.iloc[-1] < average.iloc[-4]
        and latest["high"] < previous["high"]
        and latest["low"] < previous["low"]
    )
    direction = (
        BiasDirection.LONG if bullish
        else BiasDirection.SHORT if bearish
        else None
    )
    reason = GridReason.BIAS_LOCKED if direction else GridReason.NEUTRAL_BIAS
    return BiasDecision(
        direction, reason, as_of, float(average.iloc[-1]), float(average.iloc[-4])
    )


def confirmed_pivot(
    m5: pd.DataFrame,
    as_of: pd.Timestamp,
    direction: BiasDirection,
    config: GridConfig,
) -> tuple[pd.Timestamp, float] | None:
    bars = completed_bars(m5, as_of, 5).tail(config.pivot_lookback)
    for index in range(
        len(bars) - config.pivot_right - 1, config.pivot_left - 1, -1
    ):
        row = bars.iloc[index]
        left = bars.iloc[index - config.pivot_left:index]
        right = bars.iloc[index + 1:index + config.pivot_right + 1]
        if direction is BiasDirection.LONG:
            confirmed = row["low"] < left["low"].min() and row["low"] < right["low"].min()
            price = float(row["low"])
        else:
            confirmed = row["high"] > left["high"].max() and row["high"] > right["high"].max()
            price = float(row["high"])
        if confirmed:
            return bars.index[index], price
    return None
```

Use the existing `indicators.ema` implementation, which already uses
`adjust=False`. Bullish and bearish conditions must be exact mirrors. Search
only the last `pivot_lookback` completed M5 bars and require
`pivot_left == pivot_right == 2`.

- [ ] **Step 4: Run focused and existing no-lookahead tests**

Run:

```powershell
python -m pytest tests/test_grid_bias.py tests/test_strategy.py -v
```

Expected: all tests pass; v0.x behavior is unchanged.

- [ ] **Step 5: Commit**

```powershell
git add src/gscalp/grid_bias.py tests/test_grid_bias.py tests/conftest.py
git commit -m "feat: add locked grid bias and confirmed pivots"
```

---

### Task 3: Structural Grid Geometry and Stable Rejection Reasons

**Files:**
- Create: `src/gscalp/grid_geometry.py`
- Create: `tests/test_grid_geometry.py`

**Interfaces:**
- Consumes: `BiasDecision`, session quotes, ATR, spreads, confirmed pivot, `SymbolSpec`, `GridConfig`.
- Produces: `build_grid_geometry(*, bias, session_start, anchor_bid, anchor_ask, atr, reference_spread, current_spread, spread_ceiling, pivot, symbol, config) -> GeometryDecision`.
- Produces: `basket_target(direction, fills, profit_distance, tick_size) -> float`.

- [ ] **Step 1: Add `GeometryDecision` to the model contract**

Add:

```python
@dataclass(frozen=True, slots=True)
class GeometryDecision:
    geometry: GridGeometry | None
    reason: GridReason
    diagnostics: tuple[tuple[str, float | str], ...] = ()
```

Write a test that `GeometryDecision(None, GridReason.INVALIDATION_TOO_FAR)` is immutable.

- [ ] **Step 2: Write failing long, short, and rejection tests**

Create tests that use `atr=10`, `reference_spread=0.25`, `current_spread=0.30`, `tick_size=0.01`, bullish `anchor=100`, and pivot/stop geometry yielding `D=10`.

Assert:

```python
assert decision.geometry.level_prices == (97.5, 95.0, 92.5)
assert decision.geometry.profit_distance == 2.5
assert decision.geometry.stop == 90.0
```

Mirror prices around `200` and assert the short result is symmetrical. Add exact reason tests for missing ATR/pivot, invalidation below `0.60 ATR`, above `1.50 ATR`, spread above ceiling, `Q > 0.40D`, and broker minimum distance.

- [ ] **Step 3: Verify failures**

Run:

```powershell
python -m pytest tests/test_grid_geometry.py -v
```

Expected: import failure for `gscalp.grid_geometry`.

- [ ] **Step 4: Implement conservative price rounding and geometry**

Create:

```python
def round_entry(
    price: float, direction: BiasDirection, tick_size: float
) -> float:
    units = price / tick_size
    rounded = math.floor(units) if direction is BiasDirection.LONG else math.ceil(units)
    return rounded * tick_size


def round_stop(
    price: float, direction: BiasDirection, tick_size: float
) -> float:
    units = price / tick_size
    rounded = math.floor(units) if direction is BiasDirection.LONG else math.ceil(units)
    return rounded * tick_size


def build_grid_geometry(
    *,
    bias: BiasDecision,
    session_start: pd.Timestamp,
    anchor_bid: float,
    anchor_ask: float,
    atr: float | None,
    reference_spread: float | None,
    current_spread: float,
    spread_ceiling: float,
    pivot: tuple[pd.Timestamp, float] | None,
    symbol: SymbolSpec,
    config: GridConfig,
) -> GeometryDecision:
    if bias.direction is None:
        return GeometryDecision(None, GridReason.NEUTRAL_BIAS)
    if atr is None or not math.isfinite(atr) or atr <= 0:
        return GeometryDecision(None, GridReason.ATR_UNAVAILABLE)
    if pivot is None or reference_spread is None:
        return GeometryDecision(None, GridReason.NO_CONFIRMED_PIVOT)
    anchor = anchor_ask if bias.direction is BiasDirection.LONG else anchor_bid
    buffer = max(config.stop_buffer_atr * atr,
                 config.stop_buffer_spread_multiple * reference_spread)
    raw_stop = pivot[1] - buffer if bias.direction is BiasDirection.LONG else pivot[1] + buffer
    stop = round_stop(raw_stop, bias.direction, symbol.tick_size)
    distance = abs(anchor - stop)
    if distance < config.invalidation_atr_min * atr:
        return GeometryDecision(None, GridReason.INVALIDATION_TOO_CLOSE)
    if distance > config.invalidation_atr_max * atr:
        return GeometryDecision(None, GridReason.INVALIDATION_TOO_FAR)
    if current_spread > spread_ceiling:
        return GeometryDecision(None, GridReason.SPREAD_TOO_WIDE)
    sign = -1.0 if bias.direction is BiasDirection.LONG else 1.0
    levels = tuple(
        round_entry(anchor + sign * fraction * distance,
                    bias.direction, symbol.tick_size)
        for fraction in config.level_fractions
    )
    profit_distance = max(
        config.profit_distance_fraction * distance,
        config.reference_spread_multiple * reference_spread,
        config.current_spread_multiple * current_spread,
    )
    if profit_distance > config.profit_distance_max_fraction * distance:
        return GeometryDecision(None, GridReason.SPREAD_TOO_WIDE)
    return GeometryDecision(
        GridGeometry(
            bias.direction, session_start,
            session_start + pd.Timedelta(minutes=config.session_minutes),
            anchor, stop, atr, reference_spread, current_spread,
            profit_distance, levels,
        ),
        GridReason.GRID_ARMED,
    )
```

Long anchor is ask; short anchor is bid. Stop buffer is
`max(0.10*ATR, 2*reference_spread)`. Build levels from `D` fractions and set
`Q=max(0.25D, 4*reference_spread, 2*current_spread)`. Reject before returning
prices that violate the broker's `stops_level * point`.

- [ ] **Step 5: Implement weighted basket target**

```python
def basket_target(
    direction: BiasDirection,
    fills: tuple[tuple[float, float], ...],
    profit_distance: float,
    tick_size: float,
) -> float:
    weighted = sum(price * volume for price, volume in fills) / sum(
        volume for _, volume in fills
    )
    raw = (
        weighted + profit_distance
        if direction is BiasDirection.LONG
        else weighted - profit_distance
    )
    units = raw / tick_size
    conservative = (
        math.floor(units)
        if direction is BiasDirection.LONG
        else math.ceil(units)
    )
    return conservative * tick_size
```

Long targets round down and short targets round up so research never receives favorable rounding.

- [ ] **Step 6: Run geometry and symmetry tests**

```powershell
python -m pytest tests/test_grid_geometry.py tests/test_grid_bias.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add src/gscalp/grid_models.py src/gscalp/grid_geometry.py tests/test_grid_geometry.py
git commit -m "feat: add structural grid geometry"
```

---

### Task 4: Broker-Aware Worst-Case Basket Sizing

**Files:**
- Create: `src/gscalp/grid_sizing.py`
- Create: `tests/test_grid_sizing.py`

**Interfaces:**
- Consumes: `GridGeometry`, equity/free margin, `SymbolSpec`, injected MT5-compatible calculator, `GridConfig`.
- Produces: `size_grid(*, geometry, starting_day_equity, free_margin, symbol, calculator, config, basket_id) -> PlanDecision`.

- [ ] **Step 1: Add calculator protocol and plan decision**

Define:

```python
class ProfitMarginCalculator(Protocol):
    def loss_for_one_lot(
        self, direction: BiasDirection, entry: float, stop: float
    ) -> float:
        raise NotImplementedError

    def margin_for_volume(
        self, direction: BiasDirection, volume: float, entry: float
    ) -> float:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class PlanDecision:
    plan: GridPlan | None
    reason: GridReason
    diagnostics: tuple[tuple[str, float | str], ...] = ()
```

- [ ] **Step 2: Write failing sizing tests**

Use losses of `$100`, `$70`, and `$40` per one lot, starting equity `$10,000`,
nominal risk `$20`, `volume_step=0.01`, and `volume_min=0.01`.

Assert raw equal volume is floored and the recalculated sum plus `$5` reserve is
at most `$25`. Add tests for below-minimum volume, projected loss above `$25`,
all-level margin above `$1,000` when free margin is `$10,000`, and nonnegative
or missing `order_calc_profit`.

- [ ] **Step 3: Verify failure**

```powershell
python -m pytest tests/test_grid_sizing.py -v
```

Expected: import failure for `gscalp.grid_sizing`.

- [ ] **Step 4: Implement sizing**

Create:

```python
def floor_volume(raw: float, step: float) -> float:
    return math.floor(raw / step + 1e-12) * step


def size_grid(
    *,
    geometry: GridGeometry,
    starting_day_equity: float,
    free_margin: float,
    symbol: SymbolSpec,
    calculator: ProfitMarginCalculator,
    config: GridConfig,
    basket_id: str,
) -> PlanDecision:
    losses = tuple(
        abs(calculator.loss_for_one_lot(
            geometry.direction, entry, geometry.stop
        ))
        for entry in geometry.level_prices
    )
    if any(not math.isfinite(loss) or loss <= 0 for loss in losses):
        return PlanDecision(None, GridReason.BASKET_RISK_EXCEEDED)
    nominal_cash = starting_day_equity * config.nominal_risk_fraction
    volume = floor_volume(nominal_cash / sum(losses), symbol.volume_step)
    if volume < symbol.volume_min:
        return PlanDecision(None, GridReason.VOLUME_BELOW_MINIMUM)
    projected_loss = sum(losses) * volume
    absolute_cap = starting_day_equity * config.absolute_risk_fraction
    if projected_loss > absolute_cap:
        return PlanDecision(None, GridReason.BASKET_RISK_EXCEEDED)
    margins = tuple(
        calculator.margin_for_volume(
            geometry.direction, volume, entry
        )
        for entry in geometry.level_prices
    )
    if sum(margins) > free_margin * config.max_margin_fraction:
        return PlanDecision(None, GridReason.MARGIN_LIMIT_EXCEEDED)
    levels = tuple(
        GridLevelPlan(
            number, entry, volume, geometry.stop,
            basket_target(
                geometry.direction, ((entry, volume),),
                geometry.profit_distance, symbol.tick_size,
            ),
        )
        for number, entry in enumerate(geometry.level_prices, start=1)
    )
    return PlanDecision(
        GridPlan(
            basket_id, geometry, levels,
            projected_loss, sum(margins),
        ),
        GridReason.GRID_ARMED,
    )
```

Compute one-lot stop losses at all three requested prices, calculate equal
volume from 0.20% nominal cash, floor once, recalculate losses and all margins,
and reserve the difference between 0.25% and 0.20% as cash cost capacity.
Reject rather than round upward.

- [ ] **Step 5: Implement the MT5 read-only calculator adapter**

Add `MT5ProfitMarginCalculator` in `grid_sizing.py`. It may call only
`order_calc_profit` and `order_calc_margin`; it must not expose `order_check` or
`order_send`.

- [ ] **Step 6: Run focused tests**

```powershell
python -m pytest tests/test_grid_sizing.py tests/test_mt5_read.py -v
```

Expected: all pass and no source under `grid_config`, `grid_bias`,
`grid_geometry`, or `grid_sizing` contains `order_send`.

- [ ] **Step 7: Commit**

```powershell
git add src/gscalp/grid_sizing.py src/gscalp/grid_models.py tests/test_grid_sizing.py
git commit -m "feat: add capped basket sizing"
```

---

### Task 5: Tick-Ordered Three-Level Basket Simulator

**Files:**
- Create: `src/gscalp/grid_backtest.py`
- Create: `tests/test_grid_backtest.py`

**Interfaces:**
- Consumes: `GridPlan`, UTC bid/ask ticks, completed M5 abort bars, minute-45 and minute-60 bounds, explicit cost stress.
- Produces: `simulate_grid(plan, ticks, abort_bars, costs) -> BasketResult | None`.

- [ ] **Step 1: Write failing executable-side fill tests**

Create eight named tests:

- `test_long_limits_fill_on_ask_and_exit_on_bid`: include a bid-only touch that
  does not fill and an ask touch that does.
- `test_short_limits_fill_on_bid_and_exit_on_ask`: mirror the long fixture.
- `test_target_recalculates_after_each_fill`: assert target `100.0` after E1
  and `99.5` after E2 for the declared fixture.
- `test_same_tick_gap_fill_then_stop_is_conservative`: assert a newly filled
  level stops on the same tick and never receives target profit.
- `test_unfilled_levels_expire_at_minute_45`: assert no fill at or after expiry.
- `test_open_legs_flatten_on_last_tick_before_minute_60`: assert the exact tick.
- `test_bias_abort_cancels_orders_and_closes_filled_legs`: assert executable
  close side and no later fill.
- `test_one_plan_never_creates_more_than_three_fills`: include repeated touches
  and assert one fill per level.

For a long plan with levels `(99, 98, 97)`, stop `96`, and profit distance `1`,
include a path where asks fill levels 1 and 2; assert the basket target moves
from `100` to `99.5`.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/test_grid_backtest.py -v
```

Expected: missing `gscalp.grid_backtest`.

- [ ] **Step 3: Implement explicit simulator state**

Use these internal immutable/mutable boundaries:

```python
@dataclass(slots=True)
class OpenLeg:
    level: GridLevelPlan
    fill_time: pd.Timestamp
    fill_price: float
    target: float


@dataclass(frozen=True, slots=True)
class CostStress:
    spread_multiplier: float = 1.0
    additional_cost_r: float = 0.0
    target_update_delay_ticks: int = 0
```

Validate ordered timezone-aware ticks with `bid` and `ask`. At each tick:

1. Apply stress to the executable spread.
2. Check stop/target for already open legs.
3. Apply eligible pending fills in level order.
4. Conservatively stop a newly filled leg if the same stressed tick is beyond
   the stop.
5. Recalculate the common target after fills, respecting update delay.
6. Apply bias-abort, expiry, and session-close events.

- [ ] **Step 4: Calculate basket excursions and R**

Risk denominator is `GridPlan.projected_loss_cash`. Gross cash P/L is the sum of
leg P/L. Convert gross, cost, net, MFE, and MAE to R using that denominator.
Never normalize each leg independently.

- [ ] **Step 5: Run simulator tests**

```powershell
python -m pytest tests/test_grid_backtest.py -v
```

Expected: all paths pass, including mirrored long/short fixtures.

- [ ] **Step 6: Run v0.x regression tests**

```powershell
python -m pytest tests/test_backtest.py tests/test_strategy.py -v
```

Expected: all pass unchanged.

- [ ] **Step 7: Commit**

```powershell
git add src/gscalp/grid_backtest.py tests/test_grid_backtest.py
git commit -m "feat: add tick-level grid basket simulator"
```

---

### Task 6: Basket Metrics, Stress Scenarios, Bootstrap, and Gates

**Files:**
- Create: `src/gscalp/grid_metrics.py`
- Create: `tests/test_grid_metrics.py`

**Interfaces:**
- Consumes: ordered `BasketResult` values and partition labels.
- Produces: `summarize_baskets(baskets: Iterable[BasketResult]) -> GridMetrics`.
- Produces: `bootstrap_expectancy_lower_bound(values, confidence, samples, seed) -> float`.
- Produces: `development_gate`, `validation_gate`, and `test_gate`.

- [ ] **Step 1: Write failing metric tests**

For net R `[0.40, 0.40, -1.00, 0.40]`, assert expectancy `0.05R`, profit factor
`1.2`, and drawdown `1.0R`. Test maximum consecutive losses, level-fill
distribution, forced-close rate, year share, worst basket, and spread/volatility
groups.

Add:

```python
def test_bootstrap_is_deterministic_for_fixed_seed():
    a = bootstrap_expectancy_lower_bound(
        [0.4, 0.4, -1.0, 0.4] * 30, confidence=0.90, samples=5_000, seed=260728
    )
    b = bootstrap_expectancy_lower_bound(
        [0.4, 0.4, -1.0, 0.4] * 30, confidence=0.90, samples=5_000, seed=260728
    )
    assert a == b
```

Test that development rejects 99 baskets, validation rejects 29, test rejects
19, and each gate rejects nonpositive stressed expectancy, insufficient profit
factor, drawdown above `8R`, year share above `0.35`, or a basket below `-1.10R`.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/test_grid_metrics.py -v
```

Expected: missing `gscalp.grid_metrics`.

- [ ] **Step 3: Implement metrics**

Define:

```python
@dataclass(frozen=True, slots=True)
class GridMetrics:
    basket_count: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    max_consecutive_losses: int
    average_mfe_r: float
    average_mae_r: float
    forced_close_rate: float
    average_levels_filled: float
    maximum_year_share: float
    worst_basket_r: float


def summarize_baskets(baskets: Iterable[BasketResult]) -> GridMetrics:
    items = list(baskets)
    net = np.asarray([item.net_r for item in items], dtype=float)
    wins, losses = net[net > 0], net[net < 0]
    equity = np.concatenate(([0.0], np.cumsum(net)))
    drawdown = np.maximum.accumulate(equity) - equity
    years = pd.Series([item.session_start.year for item in items]).value_counts()
    return GridMetrics(
        basket_count=len(items),
        win_rate=float(np.mean(net > 0)) if len(net) else 0.0,
        expectancy_r=float(net.mean()) if len(net) else 0.0,
        profit_factor=float(wins.sum() / abs(losses.sum())) if len(losses) else float("inf"),
        max_drawdown_r=float(drawdown.max()) if len(drawdown) else 0.0,
        max_consecutive_losses=maximum_consecutive_losses(net),
        average_mfe_r=float(np.mean([item.mfe_r for item in items])) if items else 0.0,
        average_mae_r=float(np.mean([item.mae_r for item in items])) if items else 0.0,
        forced_close_rate=float(np.mean([item.reason is GridReason.SESSION_FLATTENED for item in items])) if items else 0.0,
        average_levels_filled=float(np.mean([item.maximum_levels_filled for item in items])) if items else 0.0,
        maximum_year_share=float(years.max() / len(items)) if items else 1.0,
        worst_basket_r=float(net.min()) if len(net) else 0.0,
    )
```

Profit factor is total positive net R divided by absolute total negative net R.
Drawdown is peak-to-trough on chronological cumulative net R with a zero origin.

- [ ] **Step 4: Implement explicit gates**

```python
def development_gate(base: GridMetrics, stressed: GridMetrics) -> bool:
    return (
        base.basket_count >= 100
        and base.expectancy_r > 0
        and base.profit_factor > 1.15
        and stressed.expectancy_r > 0
        and base.max_drawdown_r <= 8.0
        and base.maximum_year_share <= 0.35
        and stressed.worst_basket_r >= -1.10
    )


def validation_gate(base: GridMetrics, stressed: GridMetrics) -> bool:
    return (
        base.basket_count >= 30
        and base.expectancy_r > 0
        and base.profit_factor > 1.15
        and stressed.expectancy_r > 0
        and base.max_drawdown_r <= 8.0
        and base.maximum_year_share <= 0.35
        and stressed.worst_basket_r >= -1.10
    )


def test_gate(
    base: GridMetrics, stressed: GridMetrics, bootstrap_lower: float
) -> bool:
    return (
        base.basket_count >= 20
        and base.expectancy_r > 0
        and base.profit_factor > 1.10
        and stressed.expectancy_r > 0
        and base.max_drawdown_r <= 8.0
        and bootstrap_lower >= -0.05
    )
```

Keep the three functions separate so gate evidence is reader-auditable.

- [ ] **Step 5: Run tests**

```powershell
python -m pytest tests/test_grid_metrics.py tests/test_metrics.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add src/gscalp/grid_metrics.py tests/test_grid_metrics.py
git commit -m "feat: add grid metrics and research gates"
```

---

### Task 7: Partition-Safe Research Pipeline and CLI

**Files:**
- Create: `src/gscalp/grid_pipeline.py`
- Create: `tests/test_grid_pipeline.py`
- Modify: `src/gscalp/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: frozen config, canonical M5/M15/tick parquet, pure grid components.
- Produces: `run_grid_research(config_path, market_root, output_dir) -> GridResearchSummary`.
- Produces CLI: `python -m gscalp.cli grid-backtest --config config/grid-v1.0.json`.

- [ ] **Step 1: Define the pipeline summary**

Add:

```python
@dataclass(frozen=True, slots=True)
class GridResearchSummary:
    version: str
    status: str
    selected_window: str | None
    development_passed: bool
    validation_passed: bool
    test_accessed: bool
    test_passed: bool
    config_sha256: str
    data_manifest_sha256: str
```

- [ ] **Step 2: Write partition-access spy tests**

Use an injected `PartitionSource` fake whose `load_validation()` and
`load_test()` append names to `calls`.

Assert with concrete temporary paths:

```python
def test_failed_development_never_reads_validation_or_test(
    tmp_path, grid_config_path, failing_development_source
):
    summary = run_grid_research(
        grid_config_path, tmp_path / "market", tmp_path / "reports",
        source=failing_development_source,
    )
    assert failing_development_source.calls == ["development"]
    assert not summary.test_accessed


def test_failed_validation_never_reads_test(
    tmp_path, grid_config_path, failing_validation_source
):
    summary = run_grid_research(
        grid_config_path, tmp_path / "market", tmp_path / "reports",
        source=failing_validation_source,
    )
    assert failing_validation_source.calls == ["development", "validation"]
    assert not summary.test_accessed


def test_passing_validation_reads_test_once(
    tmp_path, grid_config_path, passing_source
):
    summary = run_grid_research(
        grid_config_path, tmp_path / "market", tmp_path / "reports",
        source=passing_source,
    )
    assert passing_source.calls == ["development", "validation", "test"]
    assert summary.test_accessed
```

Also assert window selection uses validation stressed expectancy minus standard
error and never test metrics.

- [ ] **Step 3: Verify failure**

```powershell
python -m pytest tests/test_grid_pipeline.py -v
```

Expected: missing `gscalp.grid_pipeline`.

- [ ] **Step 4: Implement one-session evaluation**

Create internal `plan_session(*, local_date: date, window: str,
m5: pd.DataFrame, m15: pd.DataFrame, ticks: pd.DataFrame, symbol: SymbolSpec,
config: GridConfig, calculator: ProfitMarginCalculator,
starting_equity: float, free_margin: float,
spread_ceiling: float) -> SessionPlanDecision`.

It must compute New York bounds with `research.new_york_session_bounds`, use
only bars/ticks before `session_start` for bias, pivot, ATR, and reference
spread, use the first session tick as anchor, then return either a stable
rejection or a sized plan.

- [ ] **Step 5: Implement partition orchestration**

For each candidate window:

1. Evaluate development base and all declared stresses.
2. Write development metrics and rejection counts.
3. Stop if no window passes.
4. Evaluate validation for development-viable windows only.
5. Select one passing window by stressed expectancy minus standard error.
6. Evaluate that window on test exactly once.
7. Write a summary whose status is one of
   `development_rejected`, `validation_rejected`, `test_rejected`, or
   `historical_passed`.

- [ ] **Step 6: Write required artifacts atomically**

Write a temporary sibling file and `Path.replace()` it into place for:

```text
grid-v1.0-development.csv
grid-v1.0-validation.csv
grid-v1.0-test.csv
grid-v1.0-baskets.csv
grid-v1.0-legs.csv
grid-v1.0-rejections.csv
grid-v1.0-stress.csv
grid-v1.0-summary.json
```

The summary includes config and data-manifest SHA-256 hashes, partition bounds,
metrics, gate booleans, selected window, reason counts, and cost assumptions.
Convert non-finite values such as no-loss profit factor to JSON `null` and write
with `allow_nan=False`.

- [ ] **Step 7: Add the CLI command**

Extend `_parser()`:

```python
grid = commands.add_parser("grid-backtest", help="run frozen grid v1.0 research")
grid.add_argument("--config", type=Path, default=Path("config/grid-v1.0.json"))
grid.add_argument("--market-root", type=Path, default=Path("artifacts/market"))
grid.add_argument("--output", type=Path, default=Path("artifacts/reports"))
```

Extend `main(argv=None, *, mt5_module=None, research_runner=None,
recalibration_runner=None, grid_runner=None)` so tests inject a fake and
production defaults to `run_grid_research`.

- [ ] **Step 8: Run integration tests**

```powershell
python -m pytest tests/test_grid_pipeline.py tests/test_cli.py -v
```

Expected: partition access and CLI tests pass.

- [ ] **Step 9: Run the full suite**

```powershell
python -m pytest -q
```

Expected: all grid and v0.x tests pass.

- [ ] **Step 10: Commit and push the research engine**

```powershell
git add src/gscalp/grid_pipeline.py src/gscalp/cli.py tests/test_grid_pipeline.py tests/test_cli.py
git commit -m "feat: add partition-safe grid research pipeline"
git push
```

---

### Task 8: Execute Frozen Historical Research and Record the Gate Decision

**Files:**
- Generated: `artifacts/reports/grid-v1.0-*`
- Create: `docs/research/grid-v1.0-result.md`
- Conditionally create: `config/grid-v1.0-locked.json`

**Interfaces:**
- Consumes: complete Task 1-7 implementation and canonical data manifest.
- Produces: authoritative historical go/no-go evidence for the shadow plan.

- [ ] **Step 1: Verify source and data before the expensive run**

```powershell
python -m pytest -q
python -m gscalp.cli doctor --config config/strategy.json
Get-FileHash config/grid-v1.0.json -Algorithm SHA256
Get-FileHash artifacts/market/manifest.json -Algorithm SHA256
```

Expected: tests pass; doctor reports `FBS-Demo`, `XAUUSD`, and
`application_can_trade:false`.

- [ ] **Step 2: Run the frozen pipeline**

```powershell
python -m gscalp.cli grid-backtest --config config/grid-v1.0.json
```

Expected: command exits successfully and emits one of the four declared status
values. A research rejection is a valid command result, not a process failure.

- [ ] **Step 3: Validate artifacts**

Run:

```powershell
@'
import json
from pathlib import Path
import pandas as pd

root = Path("artifacts/reports")
summary = json.loads((root / "grid-v1.0-summary.json").read_text())
assert summary["status"] in {
    "development_rejected", "validation_rejected",
    "test_rejected", "historical_passed",
}
assert summary["test_accessed"] == (
    summary["status"] in {"test_rejected", "historical_passed"}
)
for name in ("baskets", "legs", "rejections", "stress"):
    pd.read_csv(root / f"grid-v1.0-{name}.csv")
print(json.dumps(summary, indent=2))
'@ | python -
```

- [ ] **Step 4: Record a committed reader summary**

Create `docs/research/grid-v1.0-result.md` containing:

- config and data hashes;
- partition access actually performed;
- per-window basket counts and gate metrics;
- selected window or rejection stage;
- base and stress expectancy/profit factor/drawdown;
- explicit statement that no demo order was attempted; and
- exact next decision.

Do not copy all raw basket rows into Git.

- [ ] **Step 5: Lock only a passing candidate**

If and only if status is `historical_passed`, create
`config/grid-v1.0-locked.json` by copying the frozen config, replacing
`candidate_sessions_ny` with the single selected window, and adding no new
thresholds. Re-run `load_grid_config` on it.

If status is rejected, do not create a locked config and do not begin the
shadow/demo implementation plan.

- [ ] **Step 6: Commit and push the historical decision**

```powershell
git add docs/research/grid-v1.0-result.md
if (Test-Path config/grid-v1.0-locked.json) {
  git add config/grid-v1.0-locked.json
}
git commit -m "docs: record grid v1.0 historical result"
git push
```

Expected: GitHub contains code, tests, frozen/locked configuration as
applicable, and the concise result; large local artifacts remain ignored.

---

## Spec Coverage

- Objective, safety constraints, session candidates, and partitions: global
  constraints plus Tasks 1, 7, and 8.
- Bias and structural invalidation: Tasks 2 and 3.
- Grid geometry and basket target: Task 3.
- Broker-aware sizing and margin: Task 4.
- Order/basket lifecycle in research: Task 5.
- Decision and rejection codes: Tasks 1, 3, 4, and 5.
- Tick-level backtesting and all declared stresses: Tasks 5 and 6.
- Research gates and artifact set: Tasks 6, 7, and 8.
- Shadow/demo promotion and live lifecycle: the conditional
  `2026-07-28-directional-grid-shadow-demo.md` plan.
- Explicit exclusions: global constraints, config invariants, maximum-fill
  simulator tests, and the live static ownership/safety audit.
