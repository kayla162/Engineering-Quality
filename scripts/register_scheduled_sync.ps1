<#
.SYNOPSIS
    把 scripts\scheduled_sync.ps1 註冊成每週執行的 Windows 排程工作（或移除）。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_scheduled_sync.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_scheduled_sync.ps1 -Day Wednesday -At 08:30
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_scheduled_sync.ps1 -Remove

.NOTES
    以目前登入的使用者身分、只在登入時執行（不儲存密碼）；錯過的排程（電腦關機）在下次開機後補跑。
    工作排程器裡的名稱：EngineeringQuality-RegulationSync。
#>
param(
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$Day = "Monday",
    [string]$At = "09:00",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$taskName = "EngineeringQuality-RegulationSync"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "已移除排程：$taskName"
    exit 0
}

$script = Join-Path $PSScriptRoot "scheduled_sync.ps1"
$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"{0}`"" -f $script) `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "工程品質系統：每週同步法規索引與目錄並檢查法規異動（scripts\scheduled_sync.ps1）" -Force | Out-Null
$task = Get-ScheduledTask -TaskName $taskName
Write-Output ("已註冊排程：{0}，每週 {1} {2}，下次執行 {3}" -f $taskName, $Day, $At, ($task | Get-ScheduledTaskInfo).NextRunTime)
