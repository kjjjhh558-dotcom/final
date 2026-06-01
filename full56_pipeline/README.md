# full56 모델 파이프라인

최종 정리 시각: 2026-06-01 13:42 KST

이 폴더는 현재 STM32 펌웨어에 탑재된 56차원 모델의 PC 학습과 변환 작업공간입니다.

## 구성

```text
scripts/run_200ms_mfcc_delta_experiment.py
  WAV 재라벨링, 56차원 특징 CSV 생성, Keras Tiny MLP 학습과 평가

scripts/export_full56_stm32_candidate.py
  Keras 모델을 TFLite로 변환하고 ST Edge AI 후보 생성

scripts/install_full56_firmware_candidate.py
  TFLite를 다시 검증하고 ST Edge AI C 코드와 DSP 표를 mouthnose 펌웨어에 설치

features/
  현재 데이터셋에서 생성한 특징 CSV

models/
  현재 Keras 모델

reports/
  현재 모델의 핵심 평가 결과

stm32_candidate/full56/model/
  현재 TFLite 모델
```

## 특징 순서

```text
static feature 17
MFCC 13
MFCC delta 13
MFCC delta-delta 13
합계 56
```

`scripts/features/extract_features.py`와 `scripts/features/dsp_features.py`는 이 폴더 바깥에 있지만, full56 코드가 필터 설계와 멜 필터뱅크 같은 공통 함수를 가져와 사용합니다.
