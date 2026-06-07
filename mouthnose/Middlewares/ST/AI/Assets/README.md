# STM32F407VET full56 AI 자산

최종 정리 시각: 2026-06-08 00:03 KST

`full56_pipeline/scripts/install_full56_firmware_candidate.py`가 생성합니다.

- 프레임: 3200 samples = 16 kHz 기준 200 ms
- 홉: 2400 samples = 150 ms
- FFT: 4096
- 특징 벡터: 56개 = static 17 + MFCC 13 + delta 13 + delta-delta 13
- Delta 문맥: MFCC 프레임 기준 전후 4칸, 약 600 ms lookahead
- 모델: Tiny MLP [16, 8], float32 STM32Cube.AI network `breath_mlp`
- 현재 TFLite 크기: 7,628 bytes
- 현재 frame accuracy: 약 76.32%
- 현재 펌웨어 DSP backend: CMSIS-DSP RFFT

자산 재설치 직전 백업은 `backups/firmware_assets/` 아래에 생성됩니다.

보드 통합 기준:

- 마이크: ICS-43434 I2S, 16 kHz PCM16
- class LED: PE0, PE1, PE2, PE3, PE7
- PA6 oral pump PWM: TIM3_CH1, 20 kHz, 기본 duty 10%
- noise profile subtraction은 현재 full56 실시간 특징 경로에 적용하지 않습니다.

## 주석 변경 메모

AI 자산 자체의 수치나 모델 파일은 이번 작업에서 재생성하지 않았습니다. 관련 Python 설치 스크립트와 STM32 wrapper 코드에 full56 자산의 생성/설치 역할 설명을 추가했습니다.
