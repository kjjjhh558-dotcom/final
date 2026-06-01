$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "build_firmware.ps1")
& (Join-Path $PSScriptRoot "flash_firmware.ps1")
