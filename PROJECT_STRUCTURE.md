# 최종 폴더 구조

최종 정리 시각: 2026-06-01 13:42 KST

## 데이터 흐름

```text
ICS-43434 마이크
-> STM32 I2S2 + DMA 수집
-> PCM16 변환, 디지털 gain 32배
-> PC의 dataset_ics43434/<label>/*.wav 저장
-> PC full56 특징 추출
-> Keras Tiny MLP 학습
-> TFLite 변환
-> ST Edge AI C 코드 생성
-> mouthnose 펌웨어에 자산 설치
-> STM32 Release 빌드 및 ST-LINK 플래시
-> STM32 내부 실시간 DSP, AI 추론, LED, 펌프 제어
```

자세 보정 정보는 별도 경로로 들어옵니다.

```text
XIAO nRF52840 IMU
-> BLE notify
-> XIAO ESP32-S3
-> USART1 UART 9600 8N1
-> STM32 PA10 RX
-> PA7 좌우 보정 공통 펌프, PB1 배기 밸브
```

## 폴더 설명

```text
final/
  dataset_ics43434/       현재 5-class WAV 데이터셋과 metadata.csv
  scripts/
    collection/           STM32 USB CDC 오디오 수집과 WAV 저장
    features/             full56가 재사용하는 PC DSP 공통 함수
    model/                full56 전체 재생성 진입점
    tools/                상태 확인, 펌프/밸브/LED/UART 점검, 빌드, 플래시
    visualization/        오디오, STM AI, MAX30102 실시간 모니터
  full56_pipeline/
    scripts/              56차원 특징 추출, Keras 학습, TFLite/ST Edge AI 변환
    features/             현재 full56 특징 CSV
    models/               현재 Keras 모델
    reports/              현재 모델 핵심 성능 결과
    stm32_candidate/      현재 TFLite 모델
  firmware_release/       다른 PC에서도 바로 플래시할 수 있는 최신 ELF 스냅샷
  mouthnose/              STM32CubeIDE 펌웨어 프로젝트
  third_party/CMSIS-DSP/  STM32 CMSIS-DSP RFFT 빌드 의존성
  wireless_bridge/        nRF52840 BLE 송신, ESP32-S3 BLE-UART 중계 스케치
  stm32_workspace/        CubeIDE headless build 전용 로컬 워크스페이스
  backups/                full56 자산을 다시 설치할 때 자동 생성되는 백업 위치
```

## full56 특징

```text
sample rate : 16000 Hz
frame       : 3200 samples = 200 ms
hop         : 2400 samples = 150 ms
overlap     : 800 samples = 50 ms
BPF         : causal Butterworth SOS, 50-2500 Hz, 4th order
window      : Hann
FFT         : CMSIS-DSP 4096 RFFT
feature     : static 17 + MFCC 13 + delta 13 + delta-delta 13 = 56
AI rate     : 약 6.67 predictions/s
```

PC 특징 추출에서는 NumPy와 SciPy를 사용합니다. STM32 실시간 실행에서는 C 코드와 CMSIS-DSP RFFT를 사용합니다. 두 결과의 일치 여부는 golden vector로 확인합니다.

## 제외 원칙

최종 폴더에는 현재 동작 재현에 필요한 파일만 둡니다. 모델 구조 탐색을 다시 시작해야 할 때는 별도 실험 폴더를 새로 만들고, 결과가 확정된 파일만 이 작업공간으로 반영하십시오.
