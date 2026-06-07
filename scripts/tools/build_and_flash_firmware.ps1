<# 
파일 설명:
  mouthnose 펌웨어를 Release 빌드한 뒤 같은 산출물을 바로 STM32 보드에 플래시합니다.

사용 시점:
  코드나 AI 자산 변경을 실제 보드에서 바로 확인하고 싶을 때 build_firmware.ps1과 flash_firmware.ps1을 한 번에 실행합니다.

실행 예:
  .\scripts\tools\build_and_flash_firmware.ps1
#>
$ErrorActionPreference = "Stop"

# 빌드 단계가 실패하면 ErrorActionPreference 때문에 플래시 단계로 넘어가지 않습니다.
& (Join-Path $PSScriptRoot "build_firmware.ps1")

# 빌드가 끝난 Release ELF 또는 firmware_release 스냅샷을 ST-LINK로 기록합니다.
& (Join-Path $PSScriptRoot "flash_firmware.ps1")
