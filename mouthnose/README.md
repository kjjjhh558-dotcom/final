# mouthnose STM32 펌웨어

최종 정리 시각: 2026-06-08 00:03 KST

이 폴더는 STM32CubeIDE에서 여는 실제 STM32F407VET6 펌웨어 프로젝트입니다.

## 주요 핀

```text
PB12 : ICS-43434 LRCLK/WS, I2S2_WS
PB13 : ICS-43434 BCLK/SCK, I2S2_CK
PB14 : ICS-43434 DOUT, I2S2ext_SD
PB8  : MAX30102 I2C1_SCL
PB9  : MAX30102 I2C1_SDA
PA6  : 구강호흡/목 에어백 펌프 PWM, TIM3_CH1
PB0  : 구강호흡/목 에어백 배기 밸브
PA7  : 좌우 보정 공통 에어백 펌프 PWM, TIM3_CH2
PB1  : 좌우 보정 공통 에어백 배기 밸브
PA10 : ESP32-S3 UART TX에서 들어오는 USART1_RX
PA9  : ESP32-S3 UART RX로 나가는 USART1_TX, 선택 연결
PE0  : mouth_exhale LED
PE1  : mouth_inhale LED
PE2  : nasal_exhale LED
PE3  : nasal_inhale LED
PE7  : noise LED
PE5  : 펌프 동작 표시 LED
PE8  : MAX30102 SpO2 상태 LED
```

## 현재 모델

```text
mic backend : ICS-43434 I2S
sample rate : 16000 Hz
PCM gain    : 32
DSP         : causal SOS BPF + Hann + CMSIS-DSP 4096 RFFT
feature     : full56
AI rate     : 약 6.67 predictions/s
boot AI     : ON
boot LED    : RAW argmax
```

## 펌프

```text
PA6 oral pump : 20 kHz PWM, 기본 duty 10%, 최대 5초
PA7 side pump : 20 kHz PWM, 기본 duty 10%, 최대 7초
PB0 oral valve: 구강호흡/목 에어백 수동 배기
PB1 side valve: IMU 자세가 NORMAL 또는 FRONT_LOW일 때 자연 배기
```

PA6 자동 동작은 최근 약 2초 동안의 예측에서 mouth LED 기준 비율이 50% 이상이고 최소 12개 예측이 모였을 때 시작합니다. 동작 중에는 중복 동작과 입력 간섭을 줄이기 위해 AI 특징 추출과 class LED 갱신을 잠시 멈춥니다.

## 빌드

상위 폴더에서 실행합니다.

```powershell
.\scripts\tools\build_firmware.ps1
.\scripts\tools\flash_firmware.ps1
```

CubeMX `.ioc`를 다시 생성하면 USER CODE와 수동 통합 부분이 영향을 받을 수 있습니다. 코드 생성 전후 diff를 반드시 확인하십시오.

## 펌웨어 코드 설명 위치

- `Core/Src/main.c`: 오디오 수집, AI 추론 패킷, LED, 펌프/밸브, IMU bridge, MAX30102 telemetry의 통합 흐름을 설명합니다.
- `Core/Src/breath_features.c`: full56 DSP feature 계산, causal 필터, FFT/MFCC, delta history를 설명합니다.
- `Core/Src/breath_ai_app.c`: STM32Cube.AI 모델 초기화, 예측, golden self-test, 실시간 추론 on/off를 설명합니다.
- `Core/Src/max30102_spo2.c`: MAX30102 I2C 레지스터 접근, sample 처리, 상태 LED를 설명합니다.
- `USB_DEVICE/App/usbd_cdc_if.c`: PC에서 들어오는 AI/LED/PLED/ACT/VALVE/IMU/MAX 텍스트 명령 처리 경로를 설명합니다.

CubeMX 재생성 후에는 USER CODE 영역의 주석과 함수 설명이 유지되는지 diff로 확인해야 합니다.
