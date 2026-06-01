param(
    [string]$ProgrammerCli = $env:STM32_PROGRAMMER_CLI
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$elf = Join-Path $root "mouthnose\Release\mouthnose.elf"
$snapshotElf = Join-Path $root "firmware_release\mouthnose.elf"

if (-not (Test-Path -LiteralPath $elf) -and (Test-Path -LiteralPath $snapshotElf)) {
    $elf = $snapshotElf
}

if (-not $ProgrammerCli) {
    $candidates = @(
        "C:\ST\STM32CubeIDE_1.18.0\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.win32_2.2.100.202412061334\tools\bin\STM32_Programmer_CLI.exe",
        "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"
    )
    $ProgrammerCli = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not $ProgrammerCli -or -not (Test-Path -LiteralPath $ProgrammerCli)) {
    throw "STM32 Programmer CLI를 찾지 못했습니다. STM32_PROGRAMMER_CLI 환경 변수에 STM32_Programmer_CLI.exe 경로를 지정하십시오."
}

if (-not (Test-Path -LiteralPath $elf)) {
    throw "플래시할 ELF 파일이 없습니다. 먼저 .\scripts\tools\build_firmware.ps1 을 실행하십시오."
}

Write-Host "STM32 Programmer : $ProgrammerCli"
Write-Host "플래시 대상 ELF  : $elf"

& $ProgrammerCli -c port=SWD freq=400 mode=UR reset=HWrst -w $elf -v -rst

if ($LASTEXITCODE -ne 0) {
    throw "ST-LINK 플래시가 실패했습니다. 종료 코드: $LASTEXITCODE"
}

Write-Host "ST-LINK 플래시 및 verify 완료"
