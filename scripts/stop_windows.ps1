<#
  start_windows.bat으로 띄운 백엔드·프런트엔드를 강제 종료한다(자식 프로세스까지).

  1. logs\*.pid 에 적힌 PID와 그 자식들을 taskkill /T /F
  2. PID 파일이 없거나 남은 것이 있으면 백엔드·화면 포트를 잡은 프로세스 중
     이 프로젝트 것(명령줄에 프로젝트 경로, "-m app serve", "vite"가 있는 것)만 종료
     포트는 logs\run.env(start가 실제로 쓴 값) → python -m app config --ports(.env.local) → 8000·5173 순으로 정한다.

  사용: stop_windows.bat
#>
param([switch]$Quiet)

$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $Root "logs"
$Utf8 = New-Object System.Text.UTF8Encoding $false
$killed = New-Object System.Collections.Generic.List[string]

function Get-Ports {
  $cfg = @{}
  $runEnv = Join-Path $Logs "run.env"
  $lines = @()
  if (Test-Path $runEnv) {
    $lines = Get-Content $runEnv -Encoding UTF8
  } else {
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $py) {
      $env:PYTHONUTF8 = "1"
      try { $lines = & $py -m app config --ports 2>$null } catch { $lines = @() }
    }
  }
  foreach ($line in $lines) { if ($line -match '^([A-Z_]+)=(\d+)$') { $cfg[$Matches[1]] = [int]$Matches[2] } }
  $ports = @()
  $ports += $(if ($cfg.PORT) { $cfg.PORT } else { 8000 })
  $ports += $(if ($cfg.WEB_PORT) { $cfg.WEB_PORT } else { 5173 })
  return $ports
}

function Stop-Tree([int]$Id, [string]$Why) {
  if (Get-Process -Id $Id -ErrorAction SilentlyContinue) {
    & taskkill.exe /PID $Id /T /F 2>&1 | Out-Null
    $killed.Add("$Why (PID $Id)")
  }
}

function Test-Ours([string]$CommandLine) {
  return $CommandLine -and ($CommandLine.Contains($Root) -or $CommandLine -match '-m app serve' -or $CommandLine -match 'vite')
}

# 포트를 잡은 프로세스에서 위로 올라가며 이 프로젝트 것(cmd 로그 리다이렉트, npm, venv 런처)까지 찾아
# 맨 위에서부터 트리째 종료한다. 자식만 죽이면 로그를 쥔 cmd가 잠깐 남는다.
function Get-OurTop([int]$Id) {
  $top = $Id
  for ($i = 0; $i -lt 6; $i++) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$top" -ErrorAction SilentlyContinue
    if (-not $proc) { break }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)" -ErrorAction SilentlyContinue
    if (-not $parent -or -not $parent.CommandLine -or -not $parent.CommandLine.Contains($Root)) { break }
    $top = [int]$parent.ProcessId
  }
  return $top
}

function Add-StopMark([string]$Log, [string]$Text) {
  for ($i = 0; $i -lt 10; $i++) {
    try { [IO.File]::AppendAllText($Log, $Text, $Utf8); return } catch { Start-Sleep -Milliseconds 200 }
  }
}

foreach ($name in @("backend", "frontend")) {
  $file = Join-Path $Logs "$name.pid"
  if (Test-Path $file) {
    $id = (Get-Content $file -Raw).Trim()
    if ($id -match '^\d+$') { Stop-Tree ([int]$id) $name }
    Remove-Item $file -Force
  }
}

Start-Sleep -Milliseconds 300
foreach ($port in (Get-Ports)) {
  $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($o in $owners) {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$o" -ErrorAction SilentlyContinue).CommandLine
    if (Test-Ours $cmd) {
      Stop-Tree (Get-OurTop ([int]$o)) "포트 $port"
    } elseif (-not $Quiet) {
      Write-Host "포트 $port 의 PID $o 은(는) 이 프로젝트 프로세스가 아니라 그대로 둬요: $cmd" -ForegroundColor Yellow
    }
  }
}
Remove-Item (Join-Path $Logs "run.env") -Force -ErrorAction SilentlyContinue

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
if ($killed.Count -gt 0) {
  foreach ($name in @("backend", "frontend")) {
    $log = Join-Path $Logs "$name.log"
    if (Test-Path $log) { Add-StopMark $log "===== $stamp 종료 (stop_windows) =====`n" }
  }
  if (-not $Quiet) {
    Write-Host "강제 종료했어요:" -ForegroundColor Green
    $killed | ForEach-Object { Write-Host "  $_" }
  }
} elseif (-not $Quiet) {
  Write-Host "실행 중인 프로세스가 없어요."
}
