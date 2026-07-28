from gscalp.pipeline import assess_historical_gate


def test_historical_gate_requires_sample_expectancy_profit_factor_and_drawdown():
    failed = assess_historical_gate(
        trade_count=1,
        test_trade_count=0,
        test_expectancy_r=0.0,
        test_profit_factor=0.0,
        max_drawdown_r=0.0,
    )
    passed = assess_historical_gate(
        trade_count=50,
        test_trade_count=10,
        test_expectancy_r=0.12,
        test_profit_factor=1.2,
        max_drawdown_r=4.0,
    )

    assert not failed
    assert passed


def test_historical_gate_rejects_excess_drawdown():
    assert not assess_historical_gate(
        trade_count=50,
        test_trade_count=10,
        test_expectancy_r=0.12,
        test_profit_factor=1.2,
        max_drawdown_r=8.1,
    )
