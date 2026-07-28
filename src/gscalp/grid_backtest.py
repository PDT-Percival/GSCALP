from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from gscalp.grid_geometry import basket_target
from gscalp.grid_models import (
    BasketResult,
    BiasDirection,
    GridLevelPlan,
    GridPlan,
    GridReason,
    LegResult,
)


_TARGET_TICK_SIZE = 0.01
_UTC_ZONE_NAMES = frozenset({"UTC", "Etc/UTC", "Etc/GMT", "GMT", "UCT", "Universal", "Zulu"})


def _is_utc(index: pd.DatetimeIndex) -> bool:
    timezone = index.tz
    if timezone is None:
        return False
    names = {
        str(timezone),
        getattr(timezone, "key", None),
        getattr(timezone, "zone", None),
        timezone.tzname(None),
    }
    return bool(names & _UTC_ZONE_NAMES) and timezone.utcoffset(None) == pd.Timedelta(0)


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

    def __post_init__(self) -> None:
        if not math.isfinite(self.spread_multiplier) or self.spread_multiplier < 1.0:
            raise ValueError("spread_multiplier must be finite and at least 1")
        if not math.isfinite(self.additional_cost_r) or self.additional_cost_r < 0:
            raise ValueError("additional_cost_r must be finite and nonnegative")
        if self.target_update_delay_ticks < 0:
            raise ValueError("target_update_delay_ticks must be nonnegative")


def _validate_ticks(ticks: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(ticks.index, pd.DatetimeIndex) or not _is_utc(ticks.index):
        raise ValueError("tick index must be timezone-aware UTC")
    if not {"bid", "ask"}.issubset(ticks.columns):
        raise ValueError("ticks must contain bid and ask columns")
    if not ticks.index.is_monotonic_increasing:
        raise ValueError("ticks must be ordered by time")
    market = ticks[["bid", "ask"]].astype(float)
    if not market.apply(lambda column: column.map(math.isfinite).all()).all():
        raise ValueError("ticks must contain finite bid and ask prices")
    if (market["ask"] < market["bid"]).any():
        raise ValueError("tick ask must be at least bid")
    return market


def _validate_abort_bars(abort_bars: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(abort_bars.index, pd.DatetimeIndex) or not _is_utc(abort_bars.index):
        raise ValueError("abort-bar index must be timezone-aware UTC")
    if "abort" not in abort_bars.columns:
        raise ValueError("abort_bars must contain abort")
    if not abort_bars.index.is_monotonic_increasing:
        raise ValueError("abort bars must be ordered by time")
    return abort_bars.loc[abort_bars["abort"].astype(bool)]


def _stressed_quote(bid: float, ask: float, stress: CostStress) -> tuple[float, float]:
    if stress.spread_multiplier == 1.0:
        return bid, ask
    midpoint = (bid + ask) / 2
    half_spread = (ask - bid) * stress.spread_multiplier / 2
    return midpoint - half_spread, midpoint + half_spread


def _should_stop(direction: BiasDirection, executable: float, stop: float) -> bool:
    return executable <= stop if direction is BiasDirection.LONG else executable >= stop


def _should_target(direction: BiasDirection, executable: float, target: float) -> bool:
    return executable >= target if direction is BiasDirection.LONG else executable <= target


def _pnl_cash(direction: BiasDirection, leg: OpenLeg, exit_price: float) -> float:
    change = exit_price - leg.fill_price
    return change * leg.level.volume if direction is BiasDirection.LONG else -change * leg.level.volume


def simulate_grid(
    plan: GridPlan,
    ticks: pd.DataFrame,
    abort_bars: pd.DataFrame,
    costs: CostStress,
) -> BasketResult | None:
    """Replay one three-level plan against ordered executable bid/ask ticks."""
    market = _validate_ticks(ticks)
    aborts = _validate_abort_bars(abort_bars)
    if plan.projected_loss_cash <= 0:
        raise ValueError("projected_loss_cash must be positive")

    geometry = plan.geometry
    active = market.loc[(market.index >= geometry.session_start) & (market.index < geometry.session_end)]
    if active.empty:
        return None
    aborts = aborts.loc[
        (aborts.index >= geometry.session_start) & (aborts.index < geometry.session_end)
    ]

    expiry = geometry.session_start + pd.Timedelta(minutes=45)
    pending = list(plan.levels)
    open_legs: list[OpenLeg] = []
    closed_legs: list[LegResult] = []
    due_target: tuple[int, float] | None = None
    maximum_levels_filled = 0
    realized_cash = 0.0
    excursion_cash = [0.0]
    final_reason: GridReason | None = None
    last_time: pd.Timestamp | None = None
    last_bid = last_ask = 0.0

    def close_leg(leg: OpenLeg, timestamp: pd.Timestamp, price: float, reason: GridReason) -> None:
        nonlocal realized_cash, final_reason
        pnl = _pnl_cash(geometry.direction, leg, price)
        realized_cash += pnl
        closed_legs.append(
            LegResult(
                leg.level.level_number, leg.fill_time, leg.fill_price, timestamp,
                price, leg.level.volume, reason, pnl,
            )
        )
        final_reason = reason

    for tick_number, (timestamp, tick) in enumerate(active.iterrows()):
        bid, ask = _stressed_quote(float(tick.bid), float(tick.ask), costs)
        last_time, last_bid, last_ask = timestamp, bid, ask

        if due_target is not None and tick_number >= due_target[0]:
            for leg in open_legs:
                leg.target = due_target[1]
            due_target = None

        terminal_exit = False
        still_open: list[OpenLeg] = []
        executable_exit = bid if geometry.direction is BiasDirection.LONG else ask
        for leg in open_legs:
            if _should_stop(geometry.direction, executable_exit, leg.level.stop):
                close_leg(leg, timestamp, executable_exit, GridReason.STOPPED)
                terminal_exit = True
            elif _should_target(geometry.direction, executable_exit, leg.target):
                close_leg(leg, timestamp, executable_exit, GridReason.TARGET_CLOSED)
                terminal_exit = True
            else:
                still_open.append(leg)
        open_legs = still_open
        if terminal_exit:
            pending.clear()

        filled_now: list[OpenLeg] = []
        if timestamp < expiry and pending:
            executable_entry = ask if geometry.direction is BiasDirection.LONG else bid
            remaining: list[GridLevelPlan] = []
            for level in pending:
                fills = (
                    executable_entry <= level.requested_price
                    if geometry.direction is BiasDirection.LONG
                    else executable_entry >= level.requested_price
                )
                if fills:
                    filled_now.append(
                        OpenLeg(level, timestamp, executable_entry, level.provisional_target)
                    )
                else:
                    remaining.append(level)
            pending = remaining
            open_legs.extend(filled_now)
            maximum_levels_filled = max(maximum_levels_filled, len(closed_legs) + len(open_legs))

        if filled_now:
            still_open = []
            for leg in open_legs:
                if leg in filled_now and _should_stop(geometry.direction, executable_exit, leg.level.stop):
                    close_leg(leg, timestamp, executable_exit, GridReason.STOPPED)
                    terminal_exit = True
                else:
                    still_open.append(leg)
            open_legs = still_open
            if terminal_exit:
                pending.clear()
            if open_legs:
                target = basket_target(
                    geometry.direction,
                    tuple((leg.fill_price, leg.level.volume) for leg in open_legs),
                    geometry.profit_distance,
                    _TARGET_TICK_SIZE,
                )
                due_target = (tick_number + costs.target_update_delay_ticks, target)
                if costs.target_update_delay_ticks == 0:
                    for leg in open_legs:
                        leg.target = target
                    due_target = None

        if timestamp >= expiry:
            pending.clear()

        if not aborts.loc[aborts.index <= timestamp].empty:
            for leg in open_legs:
                close_leg(leg, timestamp, executable_exit, GridReason.BIAS_ABORT)
            open_legs.clear()
            pending.clear()
            final_reason = GridReason.BIAS_ABORT

        marked_cash = realized_cash + sum(
            _pnl_cash(geometry.direction, leg, executable_exit) for leg in open_legs
        )
        excursion_cash.append(marked_cash)
        if final_reason is GridReason.BIAS_ABORT:
            break

    if not closed_legs and not open_legs:
        return None

    if open_legs:
        assert last_time is not None
        executable_exit = last_bid if geometry.direction is BiasDirection.LONG else last_ask
        for leg in open_legs:
            close_leg(leg, last_time, executable_exit, GridReason.SESSION_FLATTENED)
        final_reason = GridReason.SESSION_FLATTENED
        excursion_cash.append(realized_cash)

    gross_cash = sum(leg.pnl_cash for leg in closed_legs)
    denominator = plan.projected_loss_cash
    gross_r = gross_cash / denominator
    cost_r = costs.additional_cost_r
    return BasketResult(
        plan.basket_id,
        geometry.direction,
        geometry.session_start,
        max(leg.exit_time for leg in closed_legs),
        final_reason or GridReason.TARGET_CLOSED,
        tuple(closed_legs),
        gross_r,
        cost_r,
        gross_r - cost_r,
        max(excursion_cash) / denominator,
        min(excursion_cash) / denominator,
        maximum_levels_filled,
    )
