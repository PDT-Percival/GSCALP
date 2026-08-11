from __future__ import annotations

from pathlib import Path

import pandas as pd

from .news_coverage import (
    NewsCoverageItem,
    NewsCoverageReport,
    build_strategy_news_coverage_report,
)
from .news_sessions import pullback_session_spec
from .pullback_config import PullbackConfig


def build_news_coverage_report(
    config: PullbackConfig,
    market_root: Path | str,
    news_path: Path | str,
    *,
    buffer: pd.Timedelta = pd.Timedelta(0),
) -> NewsCoverageReport:
    return build_strategy_news_coverage_report(
        pullback_session_spec(config),
        market_root,
        news_path,
        buffer=buffer,
    )
