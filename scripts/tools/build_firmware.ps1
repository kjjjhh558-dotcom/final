param(
    [string]$CubeIdeCli = $env:STM32CUBEIDE_CLI
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$project = Join-Path $root "mouthnose"
$workspace = Join-Path $root "stm32_workspace"

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

$snapshotDir = Join-Path $root "firmware_release"
$snapshotElf = Join-Path $snapshotDir "mouthnose.elf"
New-Item -ItemType Directory -Path $snapshotDir -Force | Out-Null
Copy-Item -LiteralPath $elf -Destination $snapshotElf -Force

Write-Host "Release 빌드 완료: $elf"
Write-Host "배포 ELF 갱신     : $snapshotElf"
