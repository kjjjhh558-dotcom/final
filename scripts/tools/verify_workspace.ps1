$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

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

$wavCount = (Get-ChildItem -LiteralPath (Join-Path $root "dataset_ics43434") -Recurse -Filter "*.wav" | Measure-Object).Count

Write-Host "작업공간 루트 : $root"
Write-Host "WAV 파일 수   : $wavCount"

if ($missing.Count -gt 0) {
    Write-Host "누락 파일:"
    $missing | ForEach-Object { Write-Host " - $_" }
    throw "필수 파일 검증에 실패했습니다."
}

Write-Host "필수 파일 검증 완료"
