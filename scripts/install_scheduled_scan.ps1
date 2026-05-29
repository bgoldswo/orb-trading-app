<#
.SYNOPSIS
  Register a daily Windows Task Scheduler job that scans for ORB paper signals
  after the close and appends them to outputs/signals.jsonl. Places NO orders.

.PARAMETER Time
  Local time to run, HH:mm (default 16:30). NOTE: this is your machine's LOCAL
  time. The US market closes at 16:00 ET — set this to ~30 min after the close
  in YOUR timezone (e.g. 13:30 if you're on US-Pacific).

.PARAMETER TaskName
  Scheduled task name (default "ORB Daily Signal Scan").

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_scheduled_scan.ps1 -Time 16:30
#>
param(
  [string]$Time = "16:30",
  [string]$TaskName = "ORB Daily Signal Scan"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$python = Join-Path $repo ".venv\Scripts\python.exe"
$scanner = Join-Path $repo "scripts\scan_signals.py"
$logFile = Join-Path $repo "outputs\scan.log"

if (-not (Test-Path $python)) { throw "Virtual env not found at $python. Create it and 'pip install -e .[ui]' first." }
if (-not (Test-Path (Join-Path $repo "outputs"))) { New-Item -ItemType Directory -Path (Join-Path $repo "outputs") | Out-Null }

# Run via cmd so stdout/stderr are captured to outputs\scan.log for observability.
$cmdArgs = '/c ""{0}" "{1}" >> "{2}" 2>&1"' -f $python, $scanner, $logFile
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdArgs -WorkingDirectory $repo

# Weekdays only (market is closed on weekends; holidays are simply no-ops).
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -Hidden

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
  -Description "Scan for ORB paper signals (no orders). Logs to outputs/signals.jsonl." -Force | Out-Null

Write-Host "Registered '$TaskName' to run weekdays at $Time (local time)."
Write-Host "  Scanner : $python $scanner"
Write-Host "  Run log : $logFile"
Write-Host "  Signals : $(Join-Path $repo 'outputs\signals.jsonl')"
Write-Host ""
Write-Host "Adjust the time:  re-run with -Time HH:mm   |   Remove:  scripts\uninstall_scheduled_scan.ps1"
Write-Host "Run it now to test:  Start-ScheduledTask -TaskName '$TaskName'"
