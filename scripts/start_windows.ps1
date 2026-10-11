<#
  백엔드(FastAPI)와 프런트엔드(Vite)를 백그라운드로 띄운다.

  - 주소·포트: 프로젝트 루트 .env.local (HOST, PORT, WEB_HOST, WEB_PORT). 없으면 .env.example을 복사해 만든다.
    실제 값은 `python -m app config --ports`로 백엔드와 같은 규칙으로 정한다.
  - 로그: logs\backend.log, logs\frontend.log (실행할 때마다 이어 붙인다)
  - PID:  logs\backend.pid, logs\frontend.pid / 쓴 포트: logs\run.env (stop_windows.bat이 읽는다)
  - 처음 실행이면 .venv와 web\node_modules를 만든다.

  사용: start_windows.bat [-NoBrowser] [-Lan] [-AppEnv dev|prod]
    -Lan     화면을 이 PC 밖(태블릿·Tailscale)에서도 열 수 있게 한다. 개발 설정은 인증이 꺼져 있으니 믿을 수 있는 네트워크에서만.
    -AppEnv  .env.local의 APP_ENV 대신 쓸 프로필
#>
param(
  [switch]$NoBrowser,
  [switch]$Lan,
  [string]$AppEnv = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $Root "logs"
$Web = Join-Path $Root "web"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Utf8 = New-Object System.Text.UTF8Encoding $false
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

function Add-LogLine([string]$Name, [string]$Text) {
  [IO.File]::AppendAllText((Join-Path $Logs "$Name.log"), "$Text`n", $Utf8)
}

function Get-LivePid([string]$Name) {
  $file = Join-Path $Logs "$Name.pid"
  if (-not (Test-Path $file)) { return $null }
  $id = (Get-Content $file -Raw).Trim()
  if ($id -and (Get-Process -Id $id -ErrorAction SilentlyContinue)) { return [int]$id }
  Remove-Item $file -Force
  return $null
}

function Get-PortOwner([int]$Port) {
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { return $c.OwningProcess }
  return $null
}

function Require([string]$Command, [string]$Hint) {
  if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
    Write-Host "[오류] '$Command'을(를) 찾지 못했어요. $Hint" -ForegroundColor Red
    exit 1
  }
}

# 0.0.0.0 / :: 로 열어도 상태 확인은 이 PC 주소로 한다
function Get-ProbeHost([string]$BindHost) {
  if (-not $BindHost -or $BindHost -eq "0.0.0.0" -or $BindHost -eq "::") { return "127.0.0.1" }
  return $BindHost
}

# ---- 1. 처음 한 번: .env.local, 가상환경, 화면 의존성 ----
$LocalEnv = Join-Path $Root ".env.local"
if (-not (Test-Path $LocalEnv)) {
  Copy-Item (Join-Path $Root ".env.example") $LocalEnv
  Write-Host ".env.local 이 없어 .env.example 을 복사해 만들었어요. 주소·포트·Ollama 노드는 여기서 고쳐요." -ForegroundColor Yellow
}
Require "npm" "Node.js 20 이상을 설치해 주세요 (https://nodejs.org)."
if (-not (Test-Path $Py)) {
  Require "python" "Python 3.11 이상을 설치해 주세요."
  Write-Host "가상환경(.venv)을 만들어요. 처음 한 번만, 몇 분 걸려요..."
  & python -m venv (Join-Path $Root ".venv")
  if ($LASTEXITCODE -ne 0) { throw "가상환경을 만들지 못했어요" }
  & $Py -m pip install --upgrade pip
  & $Py -m pip install -e ("$Root" + "[dev]")
  if ($LASTEXITCODE -ne 0) { throw "파이썬 패키지를 설치하지 못했어요" }
}
if (-not (Test-Path (Join-Path $Web "node_modules"))) {
  Write-Host "화면 의존성(web\node_modules)을 설치해요. 처음 한 번만..."
  & npm --prefix $Web install --no-audit --no-fund
  if ($LASTEXITCODE -ne 0) { throw "npm install에 실패했어요" }
}

# ---- 2. 주소·포트 정하기 (백엔드와 같은 규칙: 기본값 < config\<APP_ENV>.env < .env.local < 환경 변수) ----
if ($AppEnv) { $env:APP_ENV = $AppEnv }
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$cfg = @{}
foreach ($line in (& $Py -m app config --ports)) {
  if ($line -match '^([A-Z_]+)=(.*)$') { $cfg[$Matches[1]] = $Matches[2] }
}
if ($LASTEXITCODE -ne 0 -or -not $cfg.PORT -or -not $cfg.WEB_PORT) { throw "설정을 읽지 못했어요 (.env.local 확인: python -m app config)" }
# 두 프로세스가 똑같은 값을 보도록 환경 변수로 넘긴다(Vite는 이 값을 .env.local보다 먼저 본다)
$env:APP_ENV = $cfg.APP_ENV
$env:HOST = $cfg.HOST
$env:PORT = $cfg.PORT
$env:WEB_HOST = $cfg.WEB_HOST
$env:WEB_PORT = $cfg.WEB_PORT
$ApiProbe = Get-ProbeHost $cfg.HOST
$WebProbe = if ($Lan) { "127.0.0.1" } else { Get-ProbeHost $cfg.WEB_HOST }
$Services = @(
  @{ Name = "backend";  Port = [int]$cfg.PORT;     Url = "http://${ApiProbe}:$($cfg.PORT)/healthz" },
  @{ Name = "frontend"; Port = [int]$cfg.WEB_PORT; Url = "http://${WebProbe}:$($cfg.WEB_PORT)/" }
)

# ---- 3. 이미 돌고 있거나 포트가 막혀 있으면 멈춘다 ----
foreach ($s in $Services) {
  $live = Get-LivePid $s.Name
  if ($live) {
    Write-Host "[중지] 이미 실행 중이에요 ($($s.Name), PID $live). 먼저 stop_windows.bat 을 실행해 주세요." -ForegroundColor Yellow
    exit 1
  }
  $owner = Get-PortOwner $s.Port
  if ($owner) {
    $pname = (Get-Process -Id $owner -ErrorAction SilentlyContinue).ProcessName
    Write-Host "[중지] 포트 $($s.Port)을(를) 다른 프로그램이 쓰고 있어요 (PID $owner, $pname)." -ForegroundColor Yellow
    Write-Host "       이 프로젝트가 띄운 것이면 stop_windows.bat 으로 끄고, 아니면 .env.local 의 $(if ($s.Name -eq 'backend') { 'PORT' } else { 'WEB_PORT' })를 바꿔 주세요."
    exit 1
  }
}

# ---- 4. 백그라운드 실행 (cmd가 출력을 로그 파일로 이어 붙인다) ----
$env:NO_COLOR = "1"        # Vite 로그에 색 코드가 섞이지 않게
$env:FORCE_COLOR = "0"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
[IO.File]::WriteAllText((Join-Path $Logs "run.env"), "PORT=$($cfg.PORT)`nWEB_PORT=$($cfg.WEB_PORT)`n", $Utf8)

$commands = @{
  backend  = "`"$Py`" -m app serve"
  frontend = "npm --prefix `"$Web`" run dev" + $(if ($Lan) { " -- --host" } else { "" })
}
$procs = @{}
foreach ($s in $Services) {
  $name = $s.Name
  $log = Join-Path $Logs "$name.log"
  Add-LogLine $name ""
  Add-LogLine $name "===== $stamp 시작 ($name, APP_ENV=$($cfg.APP_ENV), 포트 $($s.Port)) ====="
  $p = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/d /s /c `"$($commands[$name]) >> `"$log`" 2>&1`"" `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru
  [IO.File]::WriteAllText((Join-Path $Logs "$name.pid"), "$($p.Id)", $Utf8)
  $procs[$name] = $p
}

# ---- 5. 뜰 때까지 기다린다 ----
function Wait-Ready($Service, $Proc, [int]$Seconds = 90) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if ($Proc.HasExited) { return $false }
    try {
      Invoke-WebRequest -Uri $Service.Url -UseBasicParsing -TimeoutSec 2 | Out-Null
      return $true
    } catch { Start-Sleep -Milliseconds 700 }
  }
  return $false
}

Write-Host "띄우는 중..."
foreach ($s in $Services) {
  if (-not (Wait-Ready $s $procs[$s.Name])) {
    Write-Host "[실패] $($s.Name)이(가) 뜨지 않았어요. 로그 끝부분:" -ForegroundColor Red
    Get-Content (Join-Path $Logs "$($s.Name).log") -Tail 25 -Encoding UTF8 | ForEach-Object { Write-Host "  $_" }
    & (Join-Path $PSScriptRoot "stop_windows.ps1") -Quiet
    exit 1
  }
}

$WebUrl = "http://localhost:$($cfg.WEB_PORT)"
Write-Host ""
Write-Host "실행 중 (백그라운드, APP_ENV=$($cfg.APP_ENV))" -ForegroundColor Green
Write-Host "  화면:   $WebUrl   (Vite 개발 서버, 고치면 바로 반영)"
Write-Host "  백엔드: http://${ApiProbe}:$($cfg.PORT)   (API 문서 /docs)"
Write-Host "  설정:   .env.local   (지금 값 보기: .venv\Scripts\python -m app config)"
Write-Host "  로그:   logs\backend.log, logs\frontend.log"
Write-Host "  PID:    backend $($procs.backend.Id), frontend $($procs.frontend.Id)"
if ($Lan) { Write-Host "  태블릿: http://<이 PC의 Tailscale 이름 또는 IP>:$($cfg.WEB_PORT)  (logs\frontend.log의 Network 주소)" -ForegroundColor Yellow }
Write-Host "  끄기:   stop_windows.bat"
if (-not $NoBrowser) { Start-Process $WebUrl }
