# 최신 펌웨어 ELF 스냅샷

최종 정리 시각: 2026-06-01 13:47 KST

`mouthnose.elf`는 새 `final` 작업공간에서 Release clean build를 실행해 생성한 최신 스냅샷입니다.

```text
build result : 0 errors, 0 warnings
text         : 330,944 bytes
data         : 2,452 bytes
bss          : 98,772 bytes
dec          : 432,168 bytes
```

`scripts/tools/flash_firmware.ps1`는 `mouthnose/Release/mouthnose.elf`가 없으면 이 파일을 사용합니다.
