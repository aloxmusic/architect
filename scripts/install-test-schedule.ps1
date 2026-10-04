param(
    [Parameter(Mandatory)][string]$OutputRoot,
    [Parameter(Mandatory)][string]$PackageDirectory,
    [Parameter(Mandatory)][string]$BuildPython
)
$ErrorActionPreference = 'Stop'
if ((Get-TimeZone).Id -ne 'Turkey Standard Time') {
    throw 'Schedule requires Turkey Standard Time; do not silently schedule in another timezone.'
}
$taskRepo = Split-Path $PSScriptRoot -Parent
foreach ($taskPath in @((Join-Path $taskRepo '.venv\Scripts\pythonw.exe'), $PackageDirectory, $BuildPython)) {
    if (-not (Test-Path -LiteralPath $taskPath)) { throw "Required path missing: $taskPath" }
}
$taskIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskIdentity -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$taskNextHour = (Get-Date).Date.AddHours((Get-Date).Hour + 1)
$taskTriggers = @{
    quick = New-ScheduledTaskTrigger -Once -At $taskNextHour -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
    full = New-ScheduledTaskTrigger -Daily -At '03:00'
}
foreach ($taskMode in @('quick', 'full')) {
    $taskName = "Architect AI Tests - $taskMode"
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        throw "Task already exists; inspect before updating: $taskName"
    }
    $taskLauncher = Join-Path $PSScriptRoot 'continuous_tests.py'
    $taskArguments = "`"$taskLauncher`" --mode $taskMode --output `"$OutputRoot`" --package `"$PackageDirectory`" --build-python `"$BuildPython`""
    $taskAction = New-ScheduledTaskAction -Execute (Join-Path $taskRepo '.venv\Scripts\pythonw.exe') -Argument $taskArguments -WorkingDirectory $taskRepo
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTriggers[$taskMode] -Principal $taskPrincipal -Settings $taskSettings -Description 'Local Architect AI checks; no image generation or project persistence. User must be logged in.' | Out-Null
}
Get-ScheduledTask -TaskName 'Architect AI Tests - *' | Select-Object TaskName,State
