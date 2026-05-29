<#
.SYNOPSIS
  Remove the daily ORB paper-signal scheduled task.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\uninstall_scheduled_scan.ps1
#>
param([string]$TaskName = "ORB Daily Signal Scan")

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "Removed scheduled task '$TaskName'."
} else {
  Write-Host "No scheduled task named '$TaskName' found."
}
