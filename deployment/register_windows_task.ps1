# Register (or remove) a Windows Task Scheduler entry that starts Jobs Find AI
# at logon and keeps it running in the background, so scheduled searches and
# Telegram alerts work whenever you are signed in.
#
#   .\deployment\register_windows_task.ps1            # create/update the task and start it
#   .\deployment\register_windows_task.ps1 -Remove    # delete the task
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$name = "CareerPilot"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*career.main:app*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "Task '$name' removed."
    exit 0
}
$python = Join-Path $root ".venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m uvicorn career.main:app --app-dir backend --host 127.0.0.1 --port 8000" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Description "Jobs Find AI personal job assistant (local API, dashboard, scheduler)" -Force | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "Task '$name' registered and started. Dashboard: http://127.0.0.1:8000"
Write-Host "Logs are written by uvicorn to the task's console; use run.ps1 for a visible log file."
