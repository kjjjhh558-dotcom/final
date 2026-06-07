<# 
파일 설명:
  STM32_Programmer_CLI로 mouthnose.elf를 ST-LINK/SWD를 통해 STM32F407 보드에 플래시합니다.

사용 시점:
  build_firmware.ps1로 만든 Release ELF 또는 firmware_release/mouthnose.elf 스냅샷을 실제 보드에 올릴 때 실행합니다.

실행 예:
  .\scripts\tools\flash_firmware.ps1
  .\scripts\tools\flash_firmware.ps1 -ProgrammerCli "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"

주의:
  ST-LINK가 연결되어 있고 보드 전원이 켜져 있어야 하며, Programmer CLI를 찾지 못하면 STM32_PROGRAMMER_CLI 환경 변수를 지정합니다.
#>
param(
    [string]$ProgrammerCli = $env:STM32_PROGRAMMER_CLI
)

$ErrorActionPreference = "Stop"

# 우선 mouthnose/Release 산출물을 쓰고, 없으면 배포 스냅샷 firmware_release/mouthnose.elf로 대체합니다.
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$elf = Join-Path $root "mouthnose\Release\mouthnose.elf"
$snapshotElf = Join-Path $root "firmware_release\mouthnose.elf"

if (-not (Test-Path -LiteralPath $elf) -and (Test-Path -LiteralPath $snapshotElf)) {
    $elf = $snapshotElf
}

# 사용자가 지정하지 않았으면 STM32CubeIDE 번들 또는 독립 설치된 CubeProgrammer CLI를 찾습니다.
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

# SWD 400 kHz로 ELF를 쓰고 verify 후 하드웨어 reset까지 수행합니다.
& $ProgrammerCli -c port=SWD freq=400 mode=UR reset=HWrst -w $elf -v -rst

if ($LASTEXITCODE -ne 0) {
    throw "ST-LINK 플래시가 실패했습니다. 종료 코드: $LASTEXITCODE"
}

Write-Host "ST-LINK 플래시 및 verify 완료"
