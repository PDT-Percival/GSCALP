from pathlib import Path


RUNNER = Path("scripts/run_mt5_calendar_export.ps1")


def test_runner_has_exact_no_trade_startup_contract():
    source = RUNNER.read_text(encoding="utf-8")
    folded = source.casefold()

    required = {
        "AllowLiveTrading=0",
        "AllowDllImport=0",
        "Enabled=1",
        r"Script=GSCALP\GSCALP_NewsExport",
        "Symbol=XAUUSD",
        "Period=M1",
        "ShutdownTerminal=1",
        "origin.txt",
        "metaeditor64.exe",
        "terminal64.exe",
        "Start-Process",
        "-WindowStyle Hidden",
        "-PassThru",
    }
    missing = sorted(token for token in required if token not in source)
    assert not missing, f"missing runner safety tokens: {missing}"

    forbidden = {
        "stop-process",
        "taskkill",
        "remove-item -recurse",
        "/login:",
        "password=",
        "allowlivetrading=1",
    }
    present = sorted(token for token in forbidden if token in folded)
    assert not present, f"forbidden runner tokens: {present}"


def test_runner_refuses_running_terminal_and_requires_clean_compile():
    source = RUNNER.read_text(encoding="utf-8")

    assert "Get-Process" in source
    assert ".Path" in source
    assert "already running" in source
    assert "0 errors, 0 warnings" in source
    assert "GSCALP_NewsExport.ex5" in source
    assert "GSCALP_NewsExport.log" in source
    assert "$compileProcess.ExitCode -ne 0" not in source


def test_runner_requires_complete_pair_before_copying_raw_bytes():
    source = RUNNER.read_text(encoding="utf-8")

    assert "mt5_calendar_events.csv" in source
    assert "mt5_calendar_metadata.csv" in source
    assert "export_status,complete" in source
    assert "Copy-Item -LiteralPath" in source
    assert "Get-FileHash" in source
    assert "$terminalProcess.ExitCode -ne 0" not in source


def test_operations_document_exact_nontrading_workflow():
    operations = Path("docs/operations.md").read_text(encoding="utf-8")
    normalized = " ".join(operations.casefold().split())

    assert "run_mt5_calendar_export.ps1" in operations
    assert "mt5-news-import" in operations
    assert "terminal must be closed normally" in normalized
    assert "never terminates" in normalized
    assert "previous canonical news file" in normalized
