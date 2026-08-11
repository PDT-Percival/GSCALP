from pathlib import Path


SOURCE = Path("mt5/GSCALP_NewsExport.mq5")

EVENT_HEADER = (
    "query_currency,query_start_server,query_end_server,query_count,query_error,"
    "value_id,event_id,event_time_server,event_time_mode_code,event_time_mode_name,"
    "event_importance_code,event_importance_name,country_id,event_code,event_name,"
    "source_url"
)


def test_exporter_has_exact_read_only_safety_contract():
    source = SOURCE.read_text(encoding="utf-8")
    folded = source.casefold()

    required = {
        "void OnStart()",
        "CalendarValueHistory",
        "CalendarEventById",
        "CalendarCountries",
        "TERMINAL_PATH",
        "ACCOUNT_SERVER",
        "ACCOUNT_TRADE_MODE_DEMO",
        "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING",
        "CP_UTF8",
        "CALENDAR_IMPORTANCE_HIGH",
        'D\'2020.01.01 00:00:00\'',
        'D\'2026.08.01 00:00:00\'',
        EVENT_HEADER,
        '"GSCALP\\\\mt5_calendar_events.csv"',
        '"GSCALP\\\\mt5_calendar_metadata.csv"',
    }
    missing = sorted(token for token in required if token not in source)
    assert not missing, f"missing required safety-contract tokens: {missing}"

    forbidden = {
        "#include <trade/",
        "ordersend",
        "ordercheck",
        "ctrade",
        "positionopen",
        "positionclose",
        "webrequest",
        "dllimport",
        "ontick(",
        "ontimer(",
        "onchartevent(",
    }
    present = sorted(token for token in forbidden if token in folded)
    assert not present, f"forbidden trading or persistent API tokens: {present}"


def test_exporter_uses_partial_files_and_publishes_complete_metadata_last():
    source = SOURCE.read_text(encoding="utf-8")

    assert "EVENTS_PARTIAL_FILE" in source
    assert "METADATA_PARTIAL_FILE" in source
    assert 'WriteMetadataRow(metadata, "export_status", "started")' in source
    assert 'WriteMetadataRow(metadata, "export_status", "complete")' in source
    assert source.index('WriteMetadataRow(metadata, "export_status", "complete")') < source.index(
        "!PublishCompletedExport(failure)"
    )


def test_exporter_metadata_excludes_personal_and_account_value_fields():
    source = SOURCE.read_text(encoding="utf-8").casefold()

    forbidden_metadata = {
        "account_login",
        "account_name",
        "account_balance",
        "account_equity",
        "account_profit",
    }
    present = sorted(token for token in forbidden_metadata if token in source)
    assert not present, f"forbidden account metadata tokens: {present}"
