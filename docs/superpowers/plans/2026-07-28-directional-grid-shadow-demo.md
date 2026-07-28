# Directional Grid Shadow and Demo Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a restart-safe, replay-verifiable shadow controller and a separately isolated FBS-demo basket executor for a historically approved directional grid.

**Architecture:** A pure live planner consumes read-only MT5 state and writes append-only shadow events without a trading interface. A separate demo-only gateway owns pending-order submission, reconciliation, target modification, cancellation, and forced closing; it remains unreachable until historical, shadow, news, account, and explicit manual gates pass.

**Tech Stack:** Python 3.14, MetaTrader5 5.0.5735, pandas, pytest, JSONL journals, standard-library CSV/JSON/time-zone tools, Git/GitHub.

## Global Constraints

- This plan is conditional on `config/grid-v1.0-locked.json` and a committed `historical_passed` result.
- Terminal path is exactly `C:\Program Files\FBS MetaTrader 5\terminal64.exe`.
- Server is exactly `FBS-Demo`; symbol is exactly `XAUUSD`; margin mode is exactly MT5 retail hedging (`2`).
- Shadow mode has no reachable `order_check`, `order_send`, order removal, position modification, or close method.
- One basket per selected 60-minute session; three equal-volume same-direction levels.
- Worst-case basket loss including reserve is at most 0.25% starting-day equity.
- Existing XAUUSD positions or pending orders block startup.
- Every pending level has a server-side stop and provisional target.
- No automatic retry after ambiguous broker results.
- Pending levels expire at minute 45; positions flatten by minute 60.
- Missing or stale current-date news confirmation blocks demo execution.
- At least ten eligible shadow sessions with exact replay parity are required before demo review.
- An explicit user-reviewed edit from `shadow` to `demo` is required; code must never make that edit automatically.

---

## File Structure

```text
src/gscalp/grid_shadow.py                 no-trade planner, journal, restart
src/gscalp/grid_replay.py                 offline replay and parity report
src/gscalp/grid_execution.py              sole basket trade-operation owner
src/gscalp/grid_reconcile.py              broker snapshot and idempotent state
src/gscalp/grid_news.py                   explicit date confirmation/blackouts
tests/test_grid_shadow.py                 proves shadow cannot trade
tests/test_grid_replay.py                 exact parity and duplicate checks
tests/test_grid_execution.py              fake-MT5 safety and pending orders
tests/test_grid_reconcile.py              restart/ambiguity state recovery
tests/test_grid_news.py                   stale/missing/overlap rules
artifacts/shadow/grid-v1.0-events.jsonl   local append-only shadow journal
artifacts/demo/grid-v1.0-orders.jsonl     local append-only demo journal
docs/operations-grid-v1.0.md              operator commands and incidents
docs/research/grid-v1.0-shadow-result.md  committed ten-session evidence
```

---

### Task 1: Explicit News Confirmation and Live Account Snapshot

**Files:**
- Create: `src/gscalp/grid_news.py`
- Create: `tests/test_grid_news.py`
- Modify: `src/gscalp/mt5_read.py`
- Modify: `tests/test_mt5_read.py`

**Interfaces:**
- Consumes: `data/news_blackouts.csv`, selected session bounds, read-only MT5 account data.
- Produces: `news_gate(path, session_start, session_end, buffer) -> NewsDecision`.
- Produces an extended `TerminalSnapshot` containing margin mode, equity, free margin, and trade permissions.

- [ ] **Step 1: Write failing news tests**

Create:

```python
def test_empty_news_file_is_not_date_confirmation(tmp_path):
    path = tmp_path / "news.csv"
    path.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
    )
    result = news_gate(
        path,
        pd.Timestamp("2026-07-28 13:30:00+00:00"),
        pd.Timestamp("2026-07-28 14:30:00+00:00"),
        pd.Timedelta(minutes=15),
    )
    assert result.code is NewsCode.MISSING_DATE_CONFIRMATION


```

Represent a clear date with a CSV row whose `event_name` is
`NO_HIGH_IMPACT_EVENTS`, whose UTC interval covers the selected session, and
whose nonempty `source` identifies where the day was checked.

Add three more concrete tests:

- `test_overlapping_high_impact_usd_event_blocks_session` writes a USD/high row
  overlapping the buffered session and asserts `OVERLAPPING_BLACKOUT`.
- `test_explicit_source_backed_clear_day_allows_session` writes a current-date
  `NO_HIGH_IMPACT_EVENTS` row with source and asserts `CLEAR`.
- `test_stale_clear_day_does_not_confirm_today` writes only the prior date and
  asserts `MISSING_DATE_CONFIRMATION`.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/test_grid_news.py -v
```

Expected: missing `gscalp.grid_news`.

- [ ] **Step 3: Implement strict news decisions**

Define:

```python
class NewsCode(str, Enum):
    CLEAR = "clear"
    MISSING_DATE_CONFIRMATION = "missing_date_confirmation"
    OVERLAPPING_BLACKOUT = "overlapping_blackout"
    INVALID_ROW = "invalid_row"


@dataclass(frozen=True, slots=True)
class NewsDecision:
    allowed: bool
    code: NewsCode
    matching_rows: tuple[dict[str, str], ...]
```

Only explicit current-date rows with nonempty source can allow execution.
High-impact `USD` or `XAU` overlap including the pre/post buffer blocks.

- [ ] **Step 4: Extend read-only terminal snapshot tests**

Add assertions:

```python
assert snapshot.margin_mode == 2
assert snapshot.equity == 10_000.0
assert snapshot.free_margin == 9_500.0
assert snapshot.trade_allowed is True
assert snapshot.expert_allowed is True
```

The fake `account_info()` and `terminal_info()` must supply these exact values.

- [ ] **Step 5: Implement the read-only snapshot extension**

Add fields to `TerminalSnapshot` without adding any trading method:

```python
margin_mode: int
equity: float
free_margin: float
trade_allowed: bool
expert_allowed: bool
```

Read account margin mode/equity/margin_free and terminal/account permission
flags during `connect()`.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m pytest tests/test_grid_news.py tests/test_mt5_read.py -v
git add src/gscalp/grid_news.py src/gscalp/mt5_read.py tests/test_grid_news.py tests/test_mt5_read.py
git commit -m "feat: add news and account safety snapshots"
```

---

### Task 2: Append-Only Shadow Basket Planner

**Files:**
- Create: `src/gscalp/grid_shadow.py`
- Create: `tests/test_grid_shadow.py`

**Interfaces:**
- Consumes: locked config, pure `plan_session`, read-only terminal snapshot/rates/ticks.
- Produces: append-only `artifacts/shadow/grid-v1.0-events.jsonl`.
- Produces: `GridShadowController.process(snapshot) -> tuple[ShadowEvent, ...]`.

- [ ] **Step 1: Write a trading trap and failing shadow tests**

Create the following named tests with a complete fake read-only snapshot and
synthetic M5/tick stream:

```python
class TradingTrapMT5(ReadOnlyFakeMT5):
    def order_check(self, *args, **kwargs):
        raise AssertionError("shadow touched order_check")

    def order_send(self, *args, **kwargs):
        raise AssertionError("shadow touched order_send")
```

- `test_complete_shadow_session_never_accesses_trade_methods`
- `test_one_event_per_state_transition`
- `test_restart_recovers_seen_event_ids`
- `test_duplicate_tick_snapshot_is_suppressed`
- `test_shadow_rejects_incomplete_m5_abort_bar`
- `test_shadow_expires_pending_levels_at_minute_45`
- `test_shadow_flattens_hypothetical_positions_at_minute_60`

Each test must assert exact event IDs/types/timestamps, not only event counts.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/test_grid_shadow.py -v
```

Expected: missing `gscalp.grid_shadow`.

- [ ] **Step 3: Define stable shadow records**

```python
@dataclass(frozen=True, slots=True)
class ShadowEvent:
    event_id: str
    basket_id: str
    event_type: GridReason
    observed_at: pd.Timestamp
    session_start: pd.Timestamp
    payload: tuple[tuple[str, object], ...]


def event_id(
    basket_id: str, event_type: GridReason, broker_ticket: int | None, sequence: int
) -> str:
    raw = f"{basket_id}|{event_type.value}|{broker_ticket}|{sequence}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

JSONL entries include terminal/server/margin-mode identity, UTC/New York time,
config/data hash, bias inputs, grid geometry, sizing, hypothetical fills,
targets, cancellation, abort, and flat events.

- [ ] **Step 4: Implement restart-safe append**

On construction, read all existing event IDs. Reject malformed/truncated lines
with the line number; never silently discard them. Append one compact JSON
object, flush, then add the ID to memory. A repeated ID returns `False`.

- [ ] **Step 5: Implement the controller**

`GridShadowController` receives only a read-only gateway and pure planning/
simulation functions. It may call rates/ticks/positions/orders read functions
but its type must not contain a submission gateway. Recompute the current
hypothetical basket from saved events and broker-observable ticks on each
invocation.

- [ ] **Step 6: Run static safety and tests**

```powershell
python -m pytest tests/test_grid_shadow.py -v
rg -n "order_send|order_check|TRADE_ACTION" src/gscalp/grid_shadow.py
```

Expected: tests pass; ripgrep returns no matches.

- [ ] **Step 7: Commit**

```powershell
git add src/gscalp/grid_shadow.py tests/test_grid_shadow.py
git commit -m "feat: add no-trade grid shadow controller"
```

---

### Task 3: Offline Replay and Exact Shadow Parity

**Files:**
- Create: `src/gscalp/grid_replay.py`
- Create: `tests/test_grid_replay.py`

**Interfaces:**
- Consumes: shadow JSONL, saved read-only bars/ticks, locked config.
- Produces: `replay_shadow(journal_path, saved_market_path, locked_config_path) -> ReplayReport`.

- [ ] **Step 1: Write failing parity tests**

Create:

- `test_replay_matches_every_reason_price_and_state`, asserting `passed` and an
  empty mismatch tuple for an exact fixture;
- `test_replay_reports_first_mismatching_event`, changing one target by one tick
  and asserting basket/event/field/observed/replayed/source time;
- `test_replay_detects_duplicate_event_ids`, duplicating one JSONL line; and
- `test_replay_detects_decision_from_incomplete_bar`, advancing a decision
  before its M5 completion timestamp.

The mismatch report must name basket ID, event ID, field, live value, replay
value, and source tick/bar timestamp.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/test_grid_replay.py -v
```

- [ ] **Step 3: Implement replay**

Define:

```python
@dataclass(frozen=True, slots=True)
class ReplayMismatch:
    basket_id: str
    event_id: str
    field: str
    observed: object
    replayed: object
    source_time: pd.Timestamp


@dataclass(frozen=True, slots=True)
class ReplayReport:
    event_count: int
    duplicate_count: int
    incomplete_bar_count: int
    mismatches: tuple[ReplayMismatch, ...]

    @property
    def passed(self) -> bool:
        return (
            self.duplicate_count == 0
            and self.incomplete_bar_count == 0
            and not self.mismatches
        )
```

Use the same pure bias, geometry, sizing, and simulator modules as historical
research; do not duplicate trading rules in replay code.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest tests/test_grid_replay.py tests/test_grid_shadow.py -v
git add src/gscalp/grid_replay.py tests/test_grid_replay.py
git commit -m "feat: add exact shadow replay"
```

---

### Task 4: Demo-Only Pending-Order Gateway

**Files:**
- Create: `src/gscalp/grid_execution.py`
- Create: `tests/test_grid_execution.py`

**Interfaces:**
- Consumes: `GridPlan`, terminal/account snapshot, news decision, session state.
- Produces: `GridDemoGateway.arm(plan, safety) -> BasketSubmission`.
- This is the only new module allowed to call MT5 trade operations.

- [ ] **Step 1: Build a fake MT5 request recorder**

The fake must expose constants for buy/sell limits, SL/TP modification, pending
removal, deal closing, return codes, and filling/time policies. Record every
`order_check` and `order_send`.

- [ ] **Step 2: Write failing preflight tests**

Reject without calling `order_send` when:

- server is not `FBS-Demo`;
- margin mode is not `2`;
- config mode is not `demo`;
- config is not the locked hash;
- news is missing, stale, or blocked;
- session is closed or after minute 45;
- spread is above ceiling;
- basket count is one;
- any XAUUSD position or order exists;
- risk exceeds 0.25%;
- projected margin exceeds 10%;
- volume, stop, target, or broker distance is invalid; or
- terminal/account expert trading permission is false.

For the happy path, assert exactly three preflights occur before the first send,
each request has the shared structural SL, provisional TP, equal volume, unique
level comment, and v1.0 magic.

- [ ] **Step 3: Verify failure**

```powershell
python -m pytest tests/test_grid_execution.py -v
```

- [ ] **Step 4: Implement immutable safety input and result**

```python
@dataclass(frozen=True, slots=True)
class GridExecutionSafety:
    now: pd.Timestamp
    starting_day_equity: float
    current_spread: float
    spread_ceiling: float
    baskets_started: int
    existing_positions: int
    existing_orders: int
    news: NewsDecision
    config_sha256: str
    locked_config_sha256: str


@dataclass(frozen=True, slots=True)
class BasketSubmission:
    accepted: bool
    code: GridReason
    requests: tuple[dict[str, object], ...]
    results: tuple[object, ...]
```

- [ ] **Step 5: Implement all-or-stop arming**

Preflight all three requests first. If any check fails, submit none. Before
sending, append a `request_batch` journal entry containing all requests and
preflight responses.

Send in E1/E2/E3 order. Journal each result immediately. If a result is
ambiguous, stop sending subsequent levels, return `RECONCILIATION_REQUIRED`,
and do not retry.

If a later definite rejection occurs after earlier accepted pending orders,
remove only the confirmed earlier orders after reconciling their tickets.

- [ ] **Step 6: Prove no live/real path exists**

Test that constructing a config with `required_server != "FBS-Demo"` is
impossible and that runtime server mismatch rejects. There must be no accepted
mode named `live`, `real`, or `production`.

- [ ] **Step 7: Run tests and commit**

```powershell
python -m pytest tests/test_grid_execution.py tests/test_execution.py -v
git add src/gscalp/grid_execution.py tests/test_grid_execution.py
git commit -m "feat: add guarded demo grid arming"
```

---

### Task 5: Broker Reconciliation and Idempotent Basket State

**Files:**
- Create: `src/gscalp/grid_reconcile.py`
- Create: `tests/test_grid_reconcile.py`

**Interfaces:**
- Consumes: append-only demo journal, MT5 orders/positions/deals filtered by magic/basket ID.
- Produces: `reconcile_basket(basket_id, journal, broker_orders, broker_positions, broker_deals) -> Reconciliation`.
- Produces safe target modification, cancellation, bias-abort close, and session close operations through `GridDemoGateway`.

- [ ] **Step 1: Write failing reconciliation tests**

Cover these exact named tests:

- `test_restart_maps_three_order_tickets_to_one_basket`
- `test_fill_recalculates_vwap_and_common_target`
- `test_target_modification_is_idempotent`
- `test_target_result_timeout_requires_reconciliation_not_retry`
- `test_stop_on_one_leg_cancels_orders_and_closes_remaining_legs`
- `test_minute_45_cancels_only_pending_orders`
- `test_bias_abort_closes_positions_and_cancels_orders`
- `test_minute_60_closes_positions_and_cancels_orders`
- `test_foreign_magic_or_symbol_is_never_modified`

For each mutation test, assert the complete ordered list of fake-MT5 requests
and the journal stages before and after the call.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/test_grid_reconcile.py -v
```

- [ ] **Step 3: Define reconciliation state**

```python
@dataclass(frozen=True, slots=True)
class BrokerLeg:
    level_number: int
    order_ticket: int
    position_ticket: int | None
    requested_price: float
    filled_price: float | None
    volume: float
    stop: float
    target: float


@dataclass(frozen=True, slots=True)
class Reconciliation:
    basket_id: str
    legs: tuple[BrokerLeg, ...]
    pending_tickets: tuple[int, ...]
    position_tickets: tuple[int, ...]
    common_target: float | None
    ambiguous: bool
    reason: GridReason
```

- [ ] **Step 4: Implement read-before-write reconciliation**

Before every mutation:

1. Read orders, positions, and deals.
2. Filter exact symbol, magic, and basket comment.
3. Compare broker tickets and volumes with the journal.
4. Refuse mutation if any state is ambiguous.
5. Journal the intended mutation.
6. Send once.
7. Journal the result.
8. Re-read broker state before another mutation.

- [ ] **Step 5: Implement target and close operations**

Target modifications retain the original stop. Closing uses the opposite
executable market side and exact remaining position volume. A close timeout is
never resent until a read proves the position still exists with unchanged
volume.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m pytest tests/test_grid_reconcile.py tests/test_grid_execution.py -v
git add src/gscalp/grid_reconcile.py src/gscalp/grid_execution.py tests/test_grid_reconcile.py
git commit -m "feat: add restart-safe basket reconciliation"
```

---

### Task 6: CLI, Operator Runbook, and Static Safety Audit

**Files:**
- Modify: `src/gscalp/cli.py`
- Modify: `tests/test_cli.py`
- Create: `docs/operations-grid-v1.0.md`

**Interfaces:**
- Produces CLI: `grid-shadow`, `grid-replay`, and guarded `grid-demo`.
- Consumes the locked configuration and historical summary.

- [ ] **Step 1: Write failing CLI gate tests**

Assert:

- `grid-shadow` refuses without locked config/historical pass.
- `grid-replay` reports nonzero exit on mismatch.
- `grid-demo` refuses while config mode is `shadow`.
- `grid-demo` refuses with fewer than ten passing shadow sessions.
- CLI dependency injection allows fake read and execution gateways.

- [ ] **Step 2: Add commands**

```python
shadow = commands.add_parser("grid-shadow")
shadow.add_argument("--config", type=Path, default=Path("config/grid-v1.0-locked.json"))
shadow.add_argument("--journal", type=Path, default=Path("artifacts/shadow/grid-v1.0-events.jsonl"))

replay = commands.add_parser("grid-replay")
replay.add_argument("--config", type=Path, default=Path("config/grid-v1.0-locked.json"))
replay.add_argument("--journal", type=Path, default=Path("artifacts/shadow/grid-v1.0-events.jsonl"))

demo = commands.add_parser("grid-demo")
demo.add_argument("--config", type=Path, required=True)
demo.add_argument("--journal", type=Path, default=Path("artifacts/demo/grid-v1.0-orders.jsonl"))
```

`grid-demo` requires the supplied config filename to be an explicitly
user-created demo copy; the command must not modify configuration files.

- [ ] **Step 3: Write the runbook**

`docs/operations-grid-v1.0.md` must contain exact:

- doctor, shadow, replay, and demo commands;
- current-date news confirmation format;
- session and Dubai/New York time conversion check;
- start, stop, restart, and reconciliation procedures;
- how to confirm positions/orders are flat;
- ambiguous-result procedure;
- emergency manual flatten procedure in the FBS terminal;
- journal backup procedure;
- automatic return-to-shadow triggers; and
- prohibition on changing volume, levels, stop, target, or mode during session.

- [ ] **Step 4: Run static ownership audit**

```powershell
rg -n "order_send|order_check|TRADE_ACTION|ORDER_TYPE_.*LIMIT" src/gscalp
```

Expected: new trade-operation matches occur only in
`src/gscalp/grid_execution.py`; legacy matches remain isolated in the already
demo-only `src/gscalp/execution.py`.

- [ ] **Step 5: Run full tests and real read-only doctor**

```powershell
python -m pytest -q
python -m gscalp.cli doctor --config config/strategy.json
```

Expected: all tests pass; real doctor remains application read-only/shadow.

- [ ] **Step 6: Commit and push**

```powershell
git add src/gscalp/cli.py tests/test_cli.py docs/operations-grid-v1.0.md
git commit -m "feat: add grid shadow and demo operations"
git push
```

---

### Task 7: Accumulate and Verify Ten Eligible Shadow Sessions

**Files:**
- Generated: `artifacts/shadow/grid-v1.0-events.jsonl`
- Generated: `artifacts/shadow/grid-v1.0-parity.json`
- Create: `docs/research/grid-v1.0-shadow-result.md`

**Interfaces:**
- Consumes: historically locked config and live FBS-Demo read-only data.
- Produces: evidence for, but not automatic activation of, demo mode.

- [ ] **Step 1: Start only on an eligible current date**

Confirm current-date news rows, terminal identity, account margin mode, selected
New York session converted to Dubai time, no XAUUSD exposure, and normal spread.

Run:

```powershell
python -m gscalp.cli grid-shadow --config config/grid-v1.0-locked.json
```

Expected: command logs read-only state; MT5 order/deal counts do not change.

- [ ] **Step 2: Replay after each session**

```powershell
python -m gscalp.cli grid-replay --config config/grid-v1.0-locked.json
```

Expected: `passed:true`, zero duplicates, zero incomplete-bar decisions, zero
mismatches.

- [ ] **Step 3: Repeat until ten eligible sessions exist**

An eligible session has a locked bias or a reason-coded neutral/no-grid
decision, complete broker tick/rate data, explicit news confirmation, and a
successful replay. Calendar days with missing data do not count.

- [ ] **Step 4: Verify no trade actions occurred**

Compare MT5 deal/order history before and after the ten-session interval and
assert no magic/comment belonging to `grid-v1.0` exists. Record account/server,
session dates, event counts, hypothetical fills, parity, spread distribution,
and missing-data incidents.

- [ ] **Step 5: Write and commit the shadow result**

Create `docs/research/grid-v1.0-shadow-result.md` with:

- ten session dates;
- replay hashes and pass state;
- duplicate/incomplete/mismatch counts;
- observed median/90th-percentile spreads;
- historical-vs-shadow geometry comparison;
- confirmation of zero attempted orders; and
- explicit demo recommendation or continued-shadow decision.

Commit:

```powershell
git add docs/research/grid-v1.0-shadow-result.md
git commit -m "docs: record grid v1.0 shadow verification"
git push
```

---

### Task 8: Explicit Demo Promotion Review

**Files:**
- User-created only: `config/grid-v1.0-demo.json`
- Generated: `artifacts/demo/grid-v1.0-orders.jsonl`

**Interfaces:**
- Consumes: passing historical and ten-session shadow evidence.
- Produces: no action until the user explicitly approves demo activation.

- [ ] **Step 1: Present all gates to the user**

Report historical test metrics, stress metrics, shadow parity, observed spread,
broker identity, margin mode, news readiness, configured risk, and the exact
diff from locked shadow config to proposed demo config.

- [ ] **Step 2: Wait for explicit approval**

Do not create or edit a demo configuration without a user message explicitly
authorizing the mode change.

- [ ] **Step 3: Validate the user-approved demo copy**

The only permitted semantic change is:

```diff
- "mode": "shadow"
+ "mode": "demo"
```

Hash every other normalized field and require equality with the locked config.

- [ ] **Step 4: Run one guarded demo session**

Run:

```powershell
python -m gscalp.cli grid-demo --config config/grid-v1.0-demo.json
```

The executor may arm at most one three-level basket and must enforce every
runtime gate. Monitor reconciliation and confirm all orders/positions are gone
by minute 60.

- [ ] **Step 5: Return to shadow on any anomaly**

Any ambiguous broker result, parity difference, specification change, missing
news, drawdown breach, or negative rolling 40-basket expectancy requires an
explicit config reversion to shadow before another eligible session.
