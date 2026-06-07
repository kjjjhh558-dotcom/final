# 최신 펌웨어 ELF 스냅샷

최종 정리 시각: 2026-06-08 00:03 KST

`mouthnose.elf`는 새 `final` 작업공간에서 Release clean build를 실행해 생성한 최신 스냅샷입니다.

```text
build result : 0 errors, 0 warnings
text         : 330,944 bytes
data         : 2,452 bytes
bss          : 98,772 bytes
dec          : 432,168 bytes
```

`scripts/tools/flash_firmware.ps1`는 `mouthnose/Release/mouthnose.elf`가 없으면 이 파일을 사용합니다.

## 주석 변경 메모

이번 변경은 `firmware_release/mouthnose.elf` 바이너리를 다시 빌드한 것이 아니라, 소스 코드와 문서의 인수인계 설명을 보강한 작업입니다. 실제 펌웨어 동작을 바꾸려면 `scripts/tools/build_firmware.ps1`로 다시 빌드하고 산출 ELF를 갱신해야 합니다.
