import pandas as pd

from gscalp.recalibration import (
    DEVELOPMENT_SWEEP_MAXIMA,
    DEVELOPMENT_STOP_MAXIMA,
    DEVELOPMENT_SAME_BAR_RECLAIM,
    assess_development_candidate,
    select_development_candidate,
)


def test_recalibration_changes_only_one_declared_parameter_family():
    assert DEVELOPMENT_SWEEP_MAXIMA == (0.75, 1.0, 1.5)
    assert DEVELOPMENT_STOP_MAXIMA == (1.0, 1.5, 2.0, 2.5)
    assert DEVELOPMENT_SAME_BAR_RECLAIM == (True,)


def test_development_gate_requires_sample_cost_edge_drawdown_and_diversification():
    assert assess_development_candidate(
        trade_count=40,
        stressed_expectancy_r=0.12,
        profit_factor=1.2,
        max_drawdown_r=4.0,
        maximum_year_share=0.30,
    )
    assert not assess_development_candidate(
        trade_count=29,
        stressed_expectancy_r=0.12,
        profit_factor=1.2,
        max_drawdown_r=4.0,
        maximum_year_share=0.30,
    )
    assert not assess_development_candidate(
        trade_count=40,
        stressed_expectancy_r=-0.01,
        profit_factor=1.2,
        max_drawdown_r=4.0,
        maximum_year_share=0.30,
    )
    assert not assess_development_candidate(
        trade_count=40,
        stressed_expectancy_r=0.12,
        profit_factor=1.2,
        max_drawdown_r=4.0,
        maximum_year_share=0.50,
    )


def test_selection_uses_only_viable_development_rows_and_robust_score():
    grid = pd.DataFrame(
        [
            {"sweep_atr_max": 0.75, "window": "A", "development_viable": False, "robust_score": 9.0, "trade_count": 50},
            {"sweep_atr_max": 1.0, "window": "A", "development_viable": True, "robust_score": 0.08, "trade_count": 40},
            {"sweep_atr_max": 1.5, "window": "B", "development_viable": True, "robust_score": 0.04, "trade_count": 45},
        ]
    )

    selected = select_development_candidate(grid)

    assert selected == {"sweep_atr_max": 1.0, "window": "A"}
    assert select_development_candidate(grid.assign(development_viable=False)) is None


def test_selection_supports_a_separately_versioned_stop_width_experiment():
    grid = pd.DataFrame(
        [
            {"max_stop_atr": 1.0, "window": "A", "development_viable": True, "robust_score": 0.02, "trade_count": 35},
            {"max_stop_atr": 1.5, "window": "B", "development_viable": True, "robust_score": 0.07, "trade_count": 40},
        ]
    )

    assert select_development_candidate(grid, parameter="max_stop_atr") == {
        "max_stop_atr": 1.5,
        "window": "B",
    }


def test_selection_preserves_boolean_filter_values():
    grid = pd.DataFrame(
        [
            {"allow_same_bar_reclaim": True, "window": "A", "development_viable": True, "robust_score": 0.08, "trade_count": 45},
        ]
    )

    assert select_development_candidate(
        grid, parameter="allow_same_bar_reclaim"
    ) == {"allow_same_bar_reclaim": True, "window": "A"}
