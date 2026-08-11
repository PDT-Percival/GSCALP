[CmdletBinding()]
param(
    [string]$TerminalPath = 'C:\Program Files\FBS MetaTrader 5\terminal64.exe',
    [string]$MetaEditorPath = 'C:\Program Files\FBS MetaTrader 5\metaeditor64.exe',
    [string]$SourcePath = 'mt5\GSCALP_NewsExport.mq5',
    [string]$ArtifactRoot = 'artifacts\news\mt5-calendar\incoming',
    [int]$TimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$approvedTerminal = 'C:\Program Files\FBS MetaTrader 5\terminal64.exe'
$approvedMetaEditor = 'C:\Program Files\FBS MetaTrader 5\metaeditor64.exe'
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

function Resolve-RepositoryPath {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $Value))
}

function Assert-ApprovedExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $resolved = [System.IO.Path]::GetFullPath($Actual)
    if (-not [string]::Equals($resolved, $Expected, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must be the approved executable: $Expected"
    }
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "$Label does not exist: $resolved"
    }
    return $resolved
}

function Resolve-FbsDataFolder {
    param([Parameter(Mandatory = $true)][string]$InstallationDirectory)

    $terminalDataRoot = Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    if (-not (Test-Path -LiteralPath $terminalDataRoot -PathType Container)) {
        throw "MT5 terminal data root does not exist: $terminalDataRoot"
    }

    $matches = @(
        Get-ChildItem -LiteralPath $terminalDataRoot -Directory | ForEach-Object {
            $origin = Join-Path $_.FullName 'origin.txt'
            if (Test-Path -LiteralPath $origin -PathType Leaf) {
                $recordedOrigin = (Get-Content -LiteralPath $origin -Raw).Trim()
                if ([string]::Equals(
                        $recordedOrigin,
                        $InstallationDirectory,
                        [System.StringComparison]::OrdinalIgnoreCase
                    )) {
                    $_.FullName
                }
            }
        }
    )
    if ($matches.Count -ne 1) {
        throw "Expected exactly one FBS terminal data folder from origin.txt; found $($matches.Count)"
    }
    return $matches[0]
}

function Assert-TerminalNotRunning {
    param([Parameter(Mandatory = $true)][string]$ApprovedPath)

    $running = @(
        Get-Process -Name 'terminal64' -ErrorAction SilentlyContinue | Where-Object {
            try {
                $_.Path -and [string]::Equals(
                    [System.IO.Path]::GetFullPath($_.Path),
                    $ApprovedPath,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            }
            catch {
                $false
            }
        }
    )
    if ($running.Count -gt 0) {
        throw 'The approved FBS terminal is already running. Close it normally before export.'
    }
}

function Remove-ExactFileIfPresent {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        Remove-Item -LiteralPath $Path -Force
    }
}

function Assert-IdenticalFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $sourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
    $destinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
    if ($sourceHash -ne $destinationHash) {
        throw "Copied file hash mismatch: $Destination"
    }
    return $sourceHash
}

try {
    if ($TimeoutSeconds -lt 1) {
        throw 'TimeoutSeconds must be positive.'
    }

    $terminal = Assert-ApprovedExecutable -Actual $TerminalPath -Expected $approvedTerminal -Label 'TerminalPath'
    $metaEditor = Assert-ApprovedExecutable -Actual $MetaEditorPath -Expected $approvedMetaEditor -Label 'MetaEditorPath'
    $installationDirectory = Split-Path -Parent $terminal
    $source = Resolve-RepositoryPath -Value $SourcePath
    $artifactDirectory = Resolve-RepositoryPath -Value $ArtifactRoot
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Exporter source does not exist: $source"
    }

    Assert-TerminalNotRunning -ApprovedPath $terminal
    $dataFolder = Resolve-FbsDataFolder -InstallationDirectory $installationDirectory
    $scriptDirectory = Join-Path $dataFolder 'MQL5\Scripts\GSCALP'
    New-Item -ItemType Directory -Path $scriptDirectory -Force | Out-Null
    $installedSource = Join-Path $scriptDirectory 'GSCALP_NewsExport.mq5'
    $compiledScript = Join-Path $scriptDirectory 'GSCALP_NewsExport.ex5'
    $compileLog = Join-Path $scriptDirectory 'GSCALP_NewsExport.log'
    Copy-Item -LiteralPath $source -Destination $installedSource -Force
    $sourceHash = Assert-IdenticalFile -Source $source -Destination $installedSource
    Remove-ExactFileIfPresent -Path $compiledScript
    Remove-ExactFileIfPresent -Path $compileLog

    $compileArguments = @(
        "/compile:`"$installedSource`"",
        "/log:`"$compileLog`""
    )
    $compileProcess = Start-Process -FilePath $metaEditor `
        -ArgumentList $compileArguments `
        -WorkingDirectory $installationDirectory `
        -WindowStyle Hidden `
        -PassThru `
        -Wait
    if (-not (Test-Path -LiteralPath $compileLog -PathType Leaf)) {
        throw "MetaEditor did not produce the compile log: $compileLog"
    }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    if ($compileText -notmatch 'Result:\s+0 errors, 0 warnings') {
        throw "MQL5 compile did not report 0 errors, 0 warnings: $compileLog"
    }
    if (-not (Test-Path -LiteralPath $compiledScript -PathType Leaf)) {
        throw "MetaEditor did not produce GSCALP_NewsExport.ex5."
    }

    $configurationPath = Join-Path $dataFolder 'GSCALP-calendar-export.ini'
    $configuration = @'
[Experts]
AllowLiveTrading=0
AllowDllImport=0
Enabled=1

[StartUp]
Script=GSCALP\GSCALP_NewsExport
Symbol=XAUUSD
Period=M1
ShutdownTerminal=1
'@
    Set-Content -LiteralPath $configurationPath -Value $configuration -Encoding Ascii

    $terminalArguments = @("/config:`"$configurationPath`"")
    $terminalProcess = Start-Process -FilePath $terminal `
        -ArgumentList $terminalArguments `
        -WorkingDirectory $installationDirectory `
        -WindowStyle Hidden `
        -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while (-not $terminalProcess.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $terminalProcess.Refresh()
    }
    if (-not $terminalProcess.HasExited) {
        throw "MT5 calendar export timed out after $TimeoutSeconds seconds; the terminal was left running for inspection."
    }
    $terminalFiles = Join-Path $dataFolder 'MQL5\Files\GSCALP'
    $rawEvents = Join-Path $terminalFiles 'mt5_calendar_events.csv'
    $rawMetadata = Join-Path $terminalFiles 'mt5_calendar_metadata.csv'
    foreach ($requiredFile in @($rawEvents, $rawMetadata)) {
        if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
            throw "MT5 export did not produce required file: $requiredFile"
        }
    }
    $metadataText = Get-Content -LiteralPath $rawMetadata -Raw -Encoding UTF8
    if ($metadataText -notmatch '(?m)^export_status,complete\r?$') {
        throw 'MT5 metadata does not contain export_status,complete.'
    }

    New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
    $incomingEvents = Join-Path $artifactDirectory 'mt5_calendar_events.csv'
    $incomingMetadata = Join-Path $artifactDirectory 'mt5_calendar_metadata.csv'
    $eventsPartial = "$incomingEvents.partial"
    $metadataPartial = "$incomingMetadata.partial"
    Remove-ExactFileIfPresent -Path $eventsPartial
    Remove-ExactFileIfPresent -Path $metadataPartial
    Copy-Item -LiteralPath $rawEvents -Destination $eventsPartial -Force
    Copy-Item -LiteralPath $rawMetadata -Destination $metadataPartial -Force
    $eventsHash = Assert-IdenticalFile -Source $rawEvents -Destination $eventsPartial
    $metadataHash = Assert-IdenticalFile -Source $rawMetadata -Destination $metadataPartial
    Move-Item -LiteralPath $eventsPartial -Destination $incomingEvents -Force
    Move-Item -LiteralPath $metadataPartial -Destination $incomingMetadata -Force

    [ordered]@{
        status = 'complete'
        terminal_path = $terminal
        data_folder = $dataFolder
        source_sha256 = $sourceHash
        events_path = $incomingEvents
        events_sha256 = $eventsHash
        metadata_path = $incomingMetadata
        metadata_sha256 = $metadataHash
        application_can_trade = $false
    } | ConvertTo-Json -Depth 3
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
