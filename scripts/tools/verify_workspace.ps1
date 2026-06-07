<# 
파일 설명:
  프로젝트를 다른 PC로 옮긴 뒤 필수 파일과 데이터셋 WAV 수가 남아 있는지 빠르게 검증합니다.

사용 시점:
  압축 해제, Git clone, 파일 전달 직후에 README의 실행 절차를 시작하기 전 상태 점검용으로 실행합니다.

실행 예:
  .\scripts\tools\verify_workspace.ps1

검증 범위:
  데이터셋 metadata, 핵심 Python 파이프라인, full56 모델/리포트, 펌웨어 ELF, STM32 프로젝트, CMSIS-DSP, 무선 브리지 스케치를 확인합니다.
#>
$ErrorActionPreference = "Stop"

# 스크립트 위치를 기준으로 프로젝트 루트를 계산하므로 어느 디렉터리에서 실행해도 같은 경로를 검사합니다.
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

# 새 개발자가 바로 실행해야 하는 최소 파일 목록입니다. 벤더 전체를 모두 검사하지 않고 핵심 진입점만 확인합니다.
$required = @(
    "dataset_ics43434\metadata.csv",
    "scripts\collection\collect_breath_dataset.py",
    "scripts\features\dsp_features.py",
    "scripts\features\extract_features.py",
    "scripts\model\rebuild_full56_pipeline.py",
    "full56_pipeline\scripts\run_200ms_mfcc_delta_experiment.py",
    "full56_pipeline\models\mlp_200ms_mfcc_delta.keras",
    "full56_pipeline\reports\mlp_200ms_mfcc_delta_metrics.json",
    "firmware_release\mouthnose.elf",
    "mouthnose\mouthnose.ioc",
    "mouthnose\Core\Src\main.c",
    "mouthnose\Core\Src\breath_features.c",
    "mouthnose\Middlewares\ST\AI\Generated\breath_mlp.c",
    "third_party\CMSIS-DSP\Include\arm_math.h",
    "wireless_bridge\esp32s3_ble_to_stm32_uart\esp32s3_ble_to_stm32_uart.ino"
)

$missing = @()
foreach ($relative in $required) {
    $path = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $path)) {
        $missing += $relative
    }
}

# WAV 개수는 데이터셋이 실제로 포함됐는지 가장 빠르게 확인할 수 있는 건강 지표입니다.
$wavCount = (Get-ChildItem -LiteralPath (Join-Path $root "dataset_ics43434") -Recurse -Filter "*.wav" | Measure-Object).Count

Write-Host "작업공간 루트 : $root"
Write-Host "WAV 파일 수   : $wavCount"

if ($missing.Count -gt 0) {
    Write-Host "누락 파일:"
    $missing | ForEach-Object { Write-Host " - $_" }
    throw "필수 파일 검증에 실패했습니다."
}

Write-Host "필수 파일 검증 완료"
