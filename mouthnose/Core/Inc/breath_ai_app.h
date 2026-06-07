/*
 * 파일 설명:
 *   STM32Cube.AI breath_mlp 실행 wrapper API를 선언합니다.
 *   모델 초기화, feature/PCM 예측, stream 예측, golden self-test, 실시간 추론 on/off 제어가 포함됩니다.
 */

#ifndef BREATH_AI_APP_H
#define BREATH_AI_APP_H

#include <stdint.h>

#include "breath_ai_config.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    BREATH_AI_STATUS_OK = 0,
    BREATH_AI_STATUS_BAD_ARGUMENT = 1,
    BREATH_AI_STATUS_CREATE_FAILED = 2,
    BREATH_AI_STATUS_RUN_FAILED = 3,
    BREATH_AI_STATUS_MISMATCH = 4
} breath_ai_status_t;

typedef struct {
    uint32_t checked_vectors;
    uint32_t passed_vectors;
    uint8_t passed;
    float max_model_abs_error;
    uint32_t worst_model_vector;
    uint32_t worst_model_output;
    uint32_t predicted_label_mismatches;
} breath_ai_self_test_result_t;

extern volatile uint32_t breath_ai_boot_status;
extern volatile uint32_t breath_ai_boot_checked_vectors;
extern volatile uint32_t breath_ai_boot_passed_vectors;
extern volatile uint32_t breath_ai_boot_label_mismatches;
extern volatile float breath_ai_boot_max_model_abs_error;
extern volatile uint32_t breath_ai_live_inference_enabled;

/* 함수 설명: STM32Cube.AI 네트워크 핸들, 활성화 버퍼, 입출력 텐서를 초기화합니다. */
breath_ai_status_t BreathAI_Init(void);

/* 함수 설명: 정규화된 30개 특징 벡터를 모델에 넣고 5클래스 확률을 출력합니다. */
breath_ai_status_t BreathAI_Predict(
    const float features[BREATH_AI_FEATURE_COUNT],
    float probabilities[BREATH_AI_LABEL_COUNT]);

/* 함수 설명: int16 PCM 프레임에서 특징을 추출한 뒤 같은 모델 예측 경로로 전달합니다. */
breath_ai_status_t BreathAI_PredictPcmI16(
    const int16_t pcm[BREATH_AI_FRAME_SIZE],
    float probabilities[BREATH_AI_LABEL_COUNT]);

/* Push live PCM samples into the streaming DSP path. probability output is
 * valid only when prediction_ready is set to 1. */
/* 함수 설명: 실시간 PCM sample stream을 DSP history에 밀어 넣고 준비된 시점에 예측 확률을 반환합니다. */
breath_ai_status_t BreathAI_ProcessPcmI16Stream(
    const int16_t *pcm,
    uint32_t sample_count,
    float probabilities[BREATH_AI_LABEL_COUNT],
    uint8_t *prediction_ready);

/* 함수 설명: 실시간 feature history와 filter state를 초기화해 다음 예측을 새 stream처럼 시작합니다. */
void BreathAI_ResetFeatureStream(void);

/* 함수 설명: 모델 확률 배열에서 가장 큰 값을 가진 클래스 인덱스를 선택합니다. */
uint32_t BreathAI_ArgmaxProbabilities(
    const float probabilities[BREATH_AI_LABEL_COUNT]);

/* 함수 설명: PC 명령으로 제어되는 실시간 AI 추론 활성화 플래그를 설정합니다. */
void BreathAI_SetLiveInferenceEnabled(uint32_t enabled);

/* 함수 설명: 현재 실시간 AI 추론이 켜져 있는지 확인합니다. */
uint32_t BreathAI_IsLiveInferenceEnabled(void);

/* 함수 설명: golden vector를 이용해 STM 모델 출력이 기준 결과와 맞는지 검사합니다. */
breath_ai_status_t BreathAI_RunGoldenModelSelfTest(
    breath_ai_self_test_result_t *result);

/* 함수 설명: 부팅 직후 모델 self-test를 수행하고 USB CDC 로그로 결과를 전송합니다. */
void BreathAI_RunBootSelfTest(void);

#ifdef __cplusplus
}
#endif

#endif /* BREATH_AI_APP_H */
