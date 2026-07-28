from dataclasses import replace

import pandas as pd
import pytest

from gscalp.backtest import ExitReason, TradeResult
from gscalp.metrics import chronological_split, summarize
from gscalp.models import Direction


def trade(net_r: float, *, mfe_r: float = 1.0, mae_r: float = -1.0) -> TradeResult:
    timestamp = pd.Timestamp("2020-01-02 09:00:00+00:00")
    return TradeResult(
        direction=Direction.LONG,
        signal_time=timestamp,
        entry_time=timestamp,
        exit_time=timestamp,
        entry_price=100.0,
        exit_price=100.0 + net_r,
        stop=99.0,
        target=101.4,
        exit_reason=ExitReason.TARGET if net_r > 0 else ExitReason.STOP,
        gross_r=net_r,
        cost_r=0.0,
        net_r=net_r,
        mfe_r=mfe_r,
        mae_r=mae_r,
    )


def test_summary_calculates_expectancy_profit_factor_and_drawdown():
    report = summarize([trade(1.4), trade(-1.0), trade(1.4), trade(-1.0)])

    assert report.trade_count == 4
    assert report.win_rate == 0.5
    assert report.expectancy_r == pytest.approx(0.2)
    assert report.profit_factor == pytest.approx(1.4)
    assert report.max_drawdown_r == pytest.approx(1.0)
    assert report.max_consecutive_losses == 1


def test_summary_subtracts_explicit_costs():
    item = trade(1.0)
    costly = replace(item, gross_r=1.2, cost_r=0.2)

    report = summarize([costly])

    assert report.gross_expectancy_r == pytest.approx(1.2)
    assert report.expectancy_r == pytest.approx(1.0)


def test_chronological_split_preserves_order_and_untouched_test_tail():
    frame = pd.DataFrame(
        {"value": range(10)},
        index=pd.date_range("2020-01-01", periods=10, freq="D", tz="UTC"),
    )

    development, validation, test = chronological_split(frame, 0.6, 0.2)

    assert development["value"].tolist() == list(range(6))
    assert validation["value"].tolist() == [6, 7]
    assert test["value"].tolist() == [8, 9]
    assert development.index.max() < validation.index.min() < test.index.min()
