from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest

from gscalp.config import StrategyConfig
from gscalp.execution import (
    AccountState,
    DemoExecutor,
    ExecutionCode,
    SessionState,
)
from gscalp.models import Direction, ReasonCode, SignalDecision
from gscalp.mt5_read import SymbolSpec

from test_config import valid_payload


class FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    TRADE_RETCODE_DONE = 10009

    def __init__(self, loss_per_lot=-100.0):
        self.loss_per_lot = loss_per_lot
        self.checked = []
        self.sent = []

    def order_calc_profit(self, order_type, symbol, volume, entry, stop):
        return self.loss_per_lot * volume

    def order_check(self, request):
        self.checked.append(request)
        return SimpleNamespace(retcode=0, comment="ok")

    def order_send(self, request):
        self.sent.append(request)
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=123)


@pytest.fixture
def inputs(tmp_path):
    payload = valid_payload()
    payload["mode"] = "demo"
    config = StrategyConfig(**payload)
    now = pd.Timestamp("2026-07-17 13:30:00+00:00")
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2026-07-17T18:00:00Z,2026-07-17T18:30:00Z,USD,high,CPI,test\n",
        encoding="utf-8",
    )
    signal = SignalDecision(
        eligible=True,
        direction=Direction.LONG,
        signal_time=pd.Timestamp("2026-07-17 13:25:00+00:00"),
        entry=3300.0,
        stop=3298.0,
        target=3302.8,
        reasons=(ReasonCode.QUALIFIED,),
    )
    account = AccountState("FBS-Demo", 10_000.0, 10_000.0)
    spec = SymbolSpec("XAUUSD", 2, 0.01, 0.01, 1.0, 100.0, 0.01, 0.01, 0, 1)
    session = SessionState(
        now=now,
        session_start=pd.Timestamp("2026-07-17 13:00:00+00:00"),
        session_end=pd.Timestamp("2026-07-17 14:00:00+00:00"),
        realized_loss_cash=0.0,
        open_risk_cash=0.0,
        trade_count=0,
        spread=0.20,
        max_spread=0.50,
        existing_symbol_positions=0,
    )
    return config, news, signal, account, spec, session


def submit(inputs, *, mt5=None, config=None, news=None, signal=None, account=None, spec=None, session=None):
    cfg, news_path, sig, acct, symbol_spec, state = inputs
    fake = mt5 or FakeMT5()
    executor = DemoExecutor(
        fake,
        config or cfg,
        news or news_path,
        journal_path=news_path.parent / "orders.jsonl",
    )
    result = executor.submit(signal or sig, account or acct, spec or symbol_spec, session or state)
    return result, fake


def test_happy_path_sizes_with_order_calc_profit_checks_then_sends(inputs):
    result, fake = submit(inputs)

    assert result.accepted
    assert result.code is ExecutionCode.SUBMITTED
    assert result.request["volume"] == 0.25
    assert len(fake.checked) == len(fake.sent) == 1
    assert result.request["sl"] == 3298.0
    assert result.request["tp"] == 3302.8


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("server", ExecutionCode.WRONG_SERVER),
        ("mode", ExecutionCode.MODE_BLOCKED),
        ("loss", ExecutionCode.DAILY_RISK_LIMIT),
        ("count", ExecutionCode.TRADE_LIMIT),
        ("spread", ExecutionCode.SPREAD_TOO_WIDE),
        ("closed", ExecutionCode.SESSION_CLOSED),
        ("position", ExecutionCode.POSITION_EXISTS),
        ("prices", ExecutionCode.INVALID_SIGNAL),
    ],
)
def test_safety_guards_reject_without_touching_order_send(inputs, change, code):
    cfg, news, sig, acct, spec, state = inputs
    if change == "server": acct = replace(acct, server="FBS-Real")
    if change == "mode": cfg = replace(cfg, mode="shadow")
    if change == "loss": state = replace(state, realized_loss_cash=50.0, open_risk_cash=1.0)
    if change == "count": state = replace(state, trade_count=2)
    if change == "spread": state = replace(state, spread=0.51)
    if change == "closed": state = replace(state, now=state.session_end)
    if change == "position": state = replace(state, existing_symbol_positions=1)
    if change == "prices": sig = replace(sig, stop=None)

    result, fake = submit(inputs, config=cfg, signal=sig, account=acct, spec=spec, session=state)

    assert not result.accepted
    assert result.code is code
    assert fake.sent == []


def test_missing_current_date_news_blocks_execution(inputs, tmp_path):
    missing = tmp_path / "missing.csv"
    missing.write_text("event_start_utc,event_end_utc,currency,impact,event_name,source\n")

    result, fake = submit(inputs, news=missing)

    assert result.code is ExecutionCode.NEWS_DATA_MISSING
    assert fake.sent == []


def test_active_news_blackout_blocks_execution(inputs, tmp_path):
    active = tmp_path / "active.csv"
    active.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2026-07-17T13:15:00Z,2026-07-17T13:45:00Z,USD,high,CPI,test\n"
    )

    result, _ = submit(inputs, news=active)

    assert result.code is ExecutionCode.NEWS_BLACKOUT


def test_volume_below_broker_minimum_is_rejected(inputs):
    result, fake = submit(inputs, mt5=FakeMT5(loss_per_lot=-100_000.0))

    assert result.code is ExecutionCode.VOLUME_INVALID
    assert fake.sent == []


def test_proposed_order_is_included_in_daily_risk_cap(inputs):
    *_, state = inputs
    state = replace(state, realized_loss_cash=40.0)

    result, fake = submit(inputs, session=state)

    assert result.code is ExecutionCode.DAILY_RISK_LIMIT
    assert fake.sent == []


def test_submission_attempt_and_result_are_append_only_journaled(inputs):
    _, news, *_ = inputs

    result, _ = submit(inputs)

    lines = (news.parent / "orders.jsonl").read_text().splitlines()
    assert result.accepted
    assert '"stage":"request"' in lines[-2]
    assert '"stage":"result"' in lines[-1]
