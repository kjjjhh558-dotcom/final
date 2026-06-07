# BLE-UART 자세 정보 브리지

최종 정리 시각: 2026-06-08 00:03 KST

이 폴더에는 자세 정보 전체 경로를 확인하는 Arduino 스케치가 있습니다.

```text
XIAO nRF52840 IMU -> BLE notify -> XIAO ESP32-S3 -> UART -> STM32 USART1
```

STM32 배선:

```text
XIAO ESP32-S3 D6 / TX / GPIO43 -> STM32 PA10 / RX1
XIAO ESP32-S3 D7 / RX / GPIO44 -> STM32 PA9  / TX1 optional
ESP32-S3 GND        -> STM32 GND
```

프로토콜:

```text
L : 왼쪽 기울어짐
R : 오른쪽 기울어짐
N : 정상 위치
S : 스니핑 목표 각도 도달
F : 목표 각도보다 낮음
O : 목표 각도 초과
```

STM32는 한 글자 토큰과 `LEFT`, `RIGHT`, `NORMAL`, `SNIFFING`, `FRONT_LOW`, `ANGLE_OVER` 문자열을 모두 인식합니다.

STM32 최종 수신 확인:

```powershell
python .\scripts\tools\check_imu_uart_bridge.py COM4 --duration 30
```

`rx=`가 증가하면 STM32가 ESP32-S3 UART를 받고 있습니다. `valid=`가 증가하고 `state=`가 바뀌면 자세 토큰 해석도 정상입니다.

`rx=`가 계속 0이면 ESP32-S3에 UART 전용 테스트 스케치를 먼저 올립니다.

```text
wireless_bridge/esp32s3_uart_only_test/esp32s3_uart_only_test.ino
```

이 스케치는 BLE를 건너뛰고 XIAO D6/TX에서 `L/R/N/S/F/O`를 500 ms마다 보냅니다. 이 상태에서도 `rx=0`이면 BLE가 아니라 배선, 핀, 공통 GND 문제입니다.

nRF -> ESP32-S3 -> STM32 전체 경로 확인:

```powershell
python .\scripts\tools\check_nrf_ble_to_stm32_bridge.py --stm-port COM4 --esp-port COM7 --duration 30
```

이 명령은 두 USB COM 포트를 동시에 엽니다. 먼저 Arduino Serial Monitor를 닫으십시오. ESP32-S3 BLE notify/UART 송신 로그와 STM32 최종 `rx/valid` 카운터를 함께 확인합니다.

## 스케치 내부 설명

- `xiao_nrf52840_imu_ble_sender.ino`는 LSM6DS3 가속도값을 L/R/S/F/O 자세 토큰으로 분류하고 BLE notify로 보냅니다.
- `esp32s3_ble_to_stm32_uart.ino`는 SmartPillow BLE notify를 받아 STM32 USART1로 유효 토큰만 중계합니다.
- `esp32s3_uart_only_test.ino`는 BLE 없이 ESP32-S3 D6/TX -> STM32 PA10/RX1 배선만 검증합니다.

각 `.ino` 파일 맨 위에 배선과 전체 흐름을 다시 적어두었으니 업로드 전 그 설명을 먼저 확인합니다.
