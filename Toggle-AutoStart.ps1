<#
Toggle-AutoStart.ps1
Enables or disables Open WebUI auto-starting at Windows login,
using Task Scheduler. Safe to run multiple times.

Usage:
  .\Toggle-AutoStart.ps1 -Enable
  .\Toggle-AutoStart.ps1 -Disable
  .\Toggle-AutoStart.ps1            (shows current status)
#>

param(
    [switch]$Enable,
    [switch]$Disable
)

$TaskName = "OpenWebUI-AutoStart"

# Locate open-webui.exe on PATH (installed via pip, usually in Python Scripts folder)
$OpenWebUIPath = (Get-Command open-webui -ErrorAction SilentlyContinue).Source

function Show-Status {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Auto-start is currently: ENABLED" -ForegroundColor Green
        Write-Host "Open WebUI will launch automatically when you log into Windows."
    } else {
        Write-Host "Auto-start is currently: DISABLED" -ForegroundColor Yellow
        Write-Host "Use Start-OpenWebUI.bat to launch it manually, or run this script with -Enable."
    }
}

if ($Enable) {
    if (-not $OpenWebUIPath) {
        Write-Host "Could not find open-webui.exe on your PATH." -ForegroundColor Red
        Write-Host "Make sure 'pip install open-webui' completed successfully, then try again."
        exit 1
    }

    $Action = New-ScheduledTaskAction -Execute $OpenWebUIPath -Argument "serve"
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Starts Open WebUI local AI assistant at login" -Force | Out-Null

    Write-Host "Auto-start ENABLED. Open WebUI will now launch every time you log into Windows." -ForegroundColor Green
    Write-Host "Access it at http://localhost:8080 after logging in (give it ~30 seconds to start)."
}
elseif ($Disable) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Auto-start DISABLED. Use Start-OpenWebUI.bat to launch manually from now on." -ForegroundColor Yellow
    } else {
        Write-Host "Auto-start was already disabled. Nothing to do."
    }
}
else {
    Show-Status
}
