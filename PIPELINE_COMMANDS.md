# 실행 명령 모음

최종 정리 시각: 2026-06-01 13:42 KST

PowerShell에서 `final` 폴더를 현재 위치로 연 뒤 실행합니다. COM 포트 번호는 노트북마다 다를 수 있습니다.

## 1. Python 환경 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r .\requirements.txt
```

```powershell
python .\scripts\tools\list_serial_ports.py
.\scripts\tools\verify_workspace.ps1
python .\scripts\tools\report_firmware_status.py
```

## 2. ICS-43434 오디오 수집

```powershell
# 코 들숨과 날숨
python .\scripts\collection\collect_breath_dataset.py COM4 --out-dir .\dataset_ics43434 --name i2s_nasal_session --protocol nasal --sample-format pcm16 --adc-center 0 --pcm-gain 1 --pcm16-gain 1 --play-audio
```

```powershell
# 입 들숨과 날숨
python .\scripts\collection\collect_breath_dataset.py COM4 --out-dir .\dataset_ics43434 --name i2s_mouth_session --protocol mouth --sample-format pcm16 --adc-center 0 --pcm-gain 1 --pcm16-gain 1 --play-audio
```

```powershell
# 배경 소음
python .\scripts\collection\collect_breath_dataset.py COM4 --out-dir .\dataset_ics43434 --name i2s_noise_session --protocol noise --sample-format pcm16 --adc-center 0 --pcm-gain 1 --pcm16-gain 1 --play-audio
```

수집 중 기본 일시정지 키는 `p`입니다. 녹음 중인 STEP을 폐기하고 같은 STEP부터 다시 시작합니다.

## 3. full56 특징 추출, 학습, 변환, 펌웨어 자산 설치

```powershell
python .\scripts\model\rebuild_full56_pipeline.py --dataset .\dataset_ics43434
```

기존 특징 CSV를 재사용하려면 다음처럼 실행합니다.

```powershell
python .\scripts\model\rebuild_full56_pipeline.py --dataset .\dataset_ics43434 --reuse-features
```

이 명령은 다음 단계를 순서대로 수행합니다.

```text
WAV inactive frame 재라벨링
-> full56 특징 CSV 생성
-> Keras Tiny MLP 학습
-> TFLite 변환과 출력 일치 확인
-> ST Edge AI C 코드 생성
-> mouthnose/Middlewares/ST/AI 자산 교체
```

## 4. STM32 Release 빌드와 다운로드

```powershell
# Release clean build
.\scripts\tools\build_firmware.ps1
```

```powershell
# ST-LINK/SWD 플래시와 verify
.\scripts\tools\flash_firmware.ps1
```

`mouthnose/Release/mouthnose.elf`가 없으면 `firmware_release/mouthnose.elf` 스냅샷을 사용합니다. 따라서 새 노트북에서도 CubeIDE 빌드 전 현재 검증본을 바로 플래시할 수 있습니다.

```powershell
# 빌드 후 바로 플래시
.\scripts\tools\build_and_flash_firmware.ps1
```

## 5. 실시간 AI와 오디오 확인

```powershell
# STM32에 탑재된 TinyML 출력 확인
python .\scripts\visualization\stm_ai_signal_monitor.py COM4 --sample-format pcm16 --pcm16-gain 1 --no-plot --duration 100 --print-ai
```

```powershell
# STM32 TinyML 그래프
python .\scripts\visualization\stm_ai_signal_monitor.py COM4 --sample-format pcm16 --pcm16-gain 1 --draw-interval 0.05 --max-plot-points 1200 --window-sec 1.0
```

```powershell
# raw 오디오 파형과 실시간 청취
python .\scripts\visualization\realtime_signal_monitor.py COM4 --sample-format pcm16 --pcm16-gain 1 --window-sec 2 --max-plot-points 1000 --update-interval 0.12 --play-audio
```

## 6. AI, LED, 펌프, 밸브 점검

```powershell
python .\scripts\tools\set_stm_ai_inference.py COM4 on
python .\scripts\tools\set_stm_ai_inference.py COM4 off
```

```powershell
python .\scripts\tools\set_stm_led_mode.py COM4 raw
python .\scripts\tools\set_stm_led_mode.py COM4 stable
python .\scripts\tools\set_stm_led_mode.py COM4 off
```

```powershell
python .\scripts\tools\set_stm_actuator.py COM4 test --duty 10
python .\scripts\tools\set_stm_actuator.py COM4 off
python .\scripts\tools\set_stm_valve.py COM4 out
python .\scripts\tools\set_stm_valve.py COM4 off
```

## 7. BLE-UART 자세 정보 확인

무선 스케치와 배선은 [wireless_bridge/README.md](./wireless_bridge/README.md)를 확인하십시오.

```powershell
# STM32가 최종적으로 받은 UART 상태와 출력 확인
python .\scripts\tools\monitor_stm_imu_control.py COM4 --duration 60
```

```powershell
# STM32 UART 수신 카운터 확인
python .\scripts\tools\check_imu_uart_bridge.py COM4 --duration 30
```

```powershell
# ESP32-S3 USB 로그와 STM32 최종 수신을 동시에 확인
python .\scripts\tools\check_nrf_ble_to_stm32_bridge.py --stm-port COM4 --esp-port COM7 --duration 30
```

## 8. 주의 사항

- `scripts/features/extract_features.py`와 `dsp_features.py`는 full56가 공통 함수로 재사용하므로 삭제하지 않습니다.
- 펌웨어 자산 재설치 시 이전 자산은 `backups/firmware_assets/` 아래에 자동 백업됩니다.
- noise profile subtraction은 현재 STM32 full56 실시간 경로에 적용하지 않습니다.
- 다른 노트북에서는 COM 포트, CubeIDE 경로, Programmer CLI 경로를 다시 확인하십시오.
