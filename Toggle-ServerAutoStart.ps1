<#
Toggle-ServerAutoStart.ps1
Enables or disables app.py (the AI brain's server) auto-starting at Windows
login, using Task Scheduler. Runs silently in the background - no console
window popping up.

Usage:
  .\Toggle-ServerAutoStart.ps1 -Enable
  .\Toggle-ServerAutoStart.ps1 -Disable
  .\Toggle-ServerAutoStart.ps1            (shows current status)
#>

param(
    [switch]$Enable,
    [switch]$Disable
)

$TaskName = "LocalAIChat-Server"
$ScriptDir = $PSScriptRoot
$AppPath = Join-Path $ScriptDir "app.py"

# Find pythonw.exe (runs Python with no console window) rather than python.exe
$PythonCmd = Get-Command pythonw -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    $PythonCmd = Get-Command python -ErrorAction SilentlyContinue
}

function Show-Status {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Server auto-start is currently: ENABLED" -ForegroundColor Green
        Write-Host "app.py will launch automatically (silently) when you log into Windows."
        Write-Host "Check it's running with: Get-Process pythonw,python -ErrorAction SilentlyContinue"
    } else {
        Write-Host "Server auto-start is currently: DISABLED" -ForegroundColor Yellow
        Write-Host "Run 'python app.py' manually, or use this script with -Enable."
    }
}

if ($Enable) {
    if (-not $PythonCmd) {
        Write-Host "Could not find python or pythonw on your PATH." -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $AppPath)) {
        Write-Host "Could not find app.py at $AppPath" -ForegroundColor Red
        exit 1
    }

    $Action = New-ScheduledTaskAction -Execute $PythonCmd.Source -Argument "`"$AppPath`"" -WorkingDirectory $ScriptDir
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    try {
        Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Runs the Local AI Chat server (app.py) silently at login" -Force -ErrorAction Stop | Out-Null
        Write-Host "Server auto-start ENABLED." -ForegroundColor Green
        Write-Host "app.py will now launch silently every time you log into Windows."
        Write-Host "It will also auto-restart up to 3 times if it crashes."
    } catch {
        Write-Host "FAILED to enable auto-start: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "This usually means PowerShell isn't running as Administrator." -ForegroundColor Yellow
        Write-Host "Right-click PowerShell -> 'Run as administrator', then try again."
    }
}
elseif ($Disable) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Server auto-start DISABLED." -ForegroundColor Yellow
    } else {
        Write-Host "Server auto-start was already disabled. Nothing to do."
    }
}
else {
    Show-Status
}
