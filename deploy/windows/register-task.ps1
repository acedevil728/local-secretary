# 테스트(Windows PC): 로그온 시 백엔드를 자동 시작하는 작업 스케줄러 항목을 만든다.
# 프로젝트 폴더에서 PowerShell로 실행:  .\deploy\windows\register-task.ps1 -AppEnv dev
param(
  [string]$AppEnv = "dev",
  [string]$TaskName = "local-secretary"
)

$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "가상환경이 없어요: $python (python -m venv .venv 후 pip install -e .)" }

$cmd = "`$env:APP_ENV='$AppEnv'; `$env:PYTHONUTF8='1'; Set-Location '$root'; & '$python' -m app serve"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"$cmd`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "공유형 개인 비서 백엔드" -Force
Write-Host "등록함: $TaskName (APP_ENV=$AppEnv). 바로 시작하려면: Start-ScheduledTask -TaskName $TaskName"
