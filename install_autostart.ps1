<#
Keeps Saint Scernding running on this Windows PC.

  .\install_autostart.ps1              # start when you log in (no admin needed)
  .\install_autostart.ps1 -AtStartup   # start when Windows boots, even before anyone logs in (run as admin)
  .\install_autostart.ps1 -Remove      # undo

It registers a Scheduled Task called "Saint Scernding" that runs supervisor.py hidden in the background.
The supervisor restarts the bot if it ever stops. Logs go to the logs\ folder.
#>
param([switch]$AtStartup, [switch]$Remove)

$ErrorActionPreference = "Stop"
$TaskName = "Saint Scernding"
$Root = $PSScriptRoot
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*$Root*" -and $_.CommandLine -match 'supervisor\.py|bot\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Write-Host "Removed the '$TaskName' task and stopped the bot."
    return
}

if (-not (Test-Path $Pythonw)) {
    Write-Host "Setting up Python environment first..."
    py -3.11 -m venv (Join-Path $Root ".venv")
    & (Join-Path $Root ".venv\Scripts\python.exe") -m pip install -r (Join-Path $Root "requirements.txt")
}
if (-not (Test-Path (Join-Path $Root ".env"))) { throw "No .env file yet - see README.md step 3." }

$action = New-ScheduledTaskAction -Execute $Pythonw -Argument "`"$Root\supervisor.py`"" -WorkingDirectory $Root
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew
$user = "$env:USERDOMAIN\$env:USERNAME"

if ($AtStartup) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    # S4U = runs whether or not you're logged in, without storing your password
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Keeps the Saint Scernding Discord bot running" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Done! '$TaskName' will start $(if ($AtStartup) {'when Windows boots'} else {'when you log in'}) and is starting now."
Write-Host "Check on it any time with:  .venv\Scripts\python healthcheck.py"
