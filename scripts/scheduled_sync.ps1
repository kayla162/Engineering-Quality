<#
.SYNOPSIS
    每週排程用：同步全國法規索引 -> 同步行政規則與標準目錄 -> 檢查法規異動。紀錄寫在 data\logs\。

.DESCRIPTION
    由 scripts\register_scheduled_sync.ps1 註冊成 Windows 工作排程器的工作，也可以手動執行：

        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\scheduled_sync.ps1

    三個步驟的結束碼：0 = 沒有變動、2 = 有變動（正常）、其他 = 失敗。
    全國法規同步失敗時不跑後面兩步（用舊索引比對沒有意義）；目錄同步失敗仍會跑異動檢查。
    偵測到的異動出現在系統「總覽」的「法規異動」，不會自動改掉引用的狀態。
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("scheduled_sync_{0:yyyyMMdd_HHmm}.log" -f (Get-Date))

Set-Location $root
# Python 的輸出直接以 UTF-8 寫進紀錄檔（不經過 PowerShell 管線，中文才不會變亂碼）
$env:PYTHONIOENCODING = "utf-8"

function Invoke-Step([string]$script) {
    Add-Content -Path $log -Value ("`r`n==== {0}  {1:yyyy-MM-dd HH:mm:ss} ====" -f $script, (Get-Date)) -Encoding UTF8
    cmd /c "`"$python`" `"scripts\$script`" >> `"$log`" 2>&1"
    $code = $LASTEXITCODE
    Add-Content -Path $log -Value ("---- exit {0}" -f $code) -Encoding UTF8
    return $code
}

$law = Invoke-Step "sync_taiwan_law.py"
if ($law -ne 0) {
    Add-Content -Path $log -Value "全國法規同步失敗，略過目錄同步與異動檢查。" -Encoding UTF8
    exit 1
}
$catalogs = Invoke-Step "sync_catalogs.py"
$changes = Invoke-Step "check_regulation_changes.py"

$failed = @($catalogs, $changes) | Where-Object { $_ -ne 0 -and $_ -ne 2 }
Add-Content -Path $log -Value ("`r`n結果：目錄同步 {0}，異動檢查 {1}（0 沒變、2 有變、其他失敗）" -f $catalogs, $changes) -Encoding UTF8
if ($failed) { exit 1 }
exit 0
