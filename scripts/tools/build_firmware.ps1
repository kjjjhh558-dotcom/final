<# 
파일 설명:
  STM32CubeIDE headless build CLI로 mouthnose 펌웨어 Release 구성을 빌드합니다.

사용 시점:
  AI 모델 자산이나 STM32 소스가 바뀐 뒤 실제 보드에 올릴 ELF를 다시 만들 때 실행합니다.

실행 예:
  .\scripts\tools\build_firmware.ps1
  .\scripts\tools\build_firmware.ps1 -CubeIdeCli "C:\ST\STM32CubeIDE_1.19.0\STM32CubeIDE\stm32cubeidec.exe"

주의:
  STM32CubeIDE CLI 경로를 자동 탐색하지 못하면 STM32CUBEIDE_CLI 환경 변수나 -CubeIdeCli 인자로 지정해야 합니다.
#>
param(
    [string]$CubeIdeCli = $env:STM32CUBEIDE_CLI
)

$ErrorActionPreference = "Stop"

# 프로젝트 루트, STM32CubeIDE 프로젝트, headless build workspace 경로를 한 번에 계산합니다.
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$project = Join-Path $root "mouthnose"
$workspace = Join-Path $root "stm32_workspace"

# 사용자가 경로를 주지 않았으면 설치 흔적이 흔한 STM32CubeIDE CLI 후보를 순서대로 확인합니다.
if (-not $CubeIdeCli) {
    $candidates = @(
        "C:\ST\STM32CubeIDE_1.18.0\STM32CubeIDE\stm32cubeidec.exe",
        "C:\ST\STM32CubeIDE_1.19.0\STM32CubeIDE\stm32cubeidec.exe"
    )
    $CubeIdeCli = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not $CubeIdeCli -or -not (Test-Path -LiteralPath $CubeIdeCli)) {
    throw "STM32CubeIDE CLI를 찾지 못했습니다. STM32CUBEIDE_CLI 환경 변수에 stm32cubeidec.exe 경로를 지정하십시오."
}

New-Item -ItemType Directory -Path $workspace -Force | Out-Null

Write-Host "STM32CubeIDE CLI : $CubeIdeCli"
Write-Host "프로젝트         : $project"
Write-Host "워크스페이스     : $workspace"

# Eclipse CDT headless builder를 사용해 mouthnose/Release 구성을 clean build합니다.
& $CubeIdeCli `
    -nosplash `
    -application org.eclipse.cdt.managedbuilder.core.headlessbuild `
    -data $workspace `
    -import $project `
    -cleanBuild mouthnose/Release

if ($LASTEXITCODE -ne 0) {
    throw "Release 빌드가 실패했습니다. 종료 코드: $LASTEXITCODE"
}

$elf = Join-Path $project "Release\mouthnose.elf"
if (-not (Test-Path -LiteralPath $elf)) {
    throw "빌드는 끝났지만 ELF 파일을 찾지 못했습니다: $elf"
}

# 플래시 스크립트와 다른 PC에서도 바로 쓸 수 있게 최신 Release ELF를 firmware_release에 복사합니다.
$snapshotDir = Join-Path $root "firmware_release"
$snapshotElf = Join-Path $snapshotDir "mouthnose.elf"
New-Item -ItemType Directory -Path $snapshotDir -Force | Out-Null
Copy-Item -LiteralPath $elf -Destination $snapshotElf -Force

Write-Host "Release 빌드 완료: $elf"
Write-Host "배포 ELF 갱신     : $snapshotElf"
