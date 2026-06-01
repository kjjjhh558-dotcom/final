/* 파일 설명: STM32Cube.AI로 생성된 MLP 모델을 초기화하고, 특징 벡터 또는 PCM 프레임을 입력받아 5클래스 호흡 확률을 계산합니다. */

#include "breath_ai_app.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "main.h"
#include "usbd_cdc_if.h"

#include "ai_platform.h"
#include "breath_features.h"
#include "breath_golden_vectors.h"
#include "breath_mlp.h"
#include "breath_mlp_data.h"

AI_ALIGNED(4) static ai_u8 s_breath_ai_activations[AI_BREATH_MLP_DATA_ACTIVATIONS_SIZE];
AI_ALIGNED(4) static float s_breath_ai_input[BREATH_AI_FEATURE_COUNT];
AI_ALIGNED(4) static float s_breath_ai_output[BREATH_AI_LABEL_COUNT];
static breath_feature_scratch_t s_breath_ai_feature_scratch;

static ai_handle s_breath_ai_network = AI_HANDLE_NULL;

volatile uint32_t breath_ai_boot_status = BREATH_AI_STATUS_CREATE_FAILED;
volatile uint32_t breath_ai_boot_checked_vectors = 0U;
volatile uint32_t breath_ai_boot_passed_vectors = 0U;
volatile uint32_t breath_ai_boot_label_mismatches = 0U;
volatile float breath_ai_boot_max_model_abs_error = 0.0f;
volatile uint32_t breath_ai_live_inference_enabled = 1U;

/* 함수 설명: self-test 결과 구조체를 기본 통과 상태로 초기화합니다. */
static void BreathAI_ResetSelfTestResult(breath_ai_self_test_result_t *result)
{
    if (result != NULL) {
        memset(result, 0, sizeof(*result));
        result->passed = 1U;
    }
}

/* 함수 설명: 주어진 float 배열에서 최댓값 위치를 찾는 내부 유틸리티입니다. */
static uint32_t BreathAI_Argmax(const float *values, uint32_t count)
{
    uint32_t best_index = 0U;
    float best_value = values[0];

    for (uint32_t i = 1U; i < count; ++i) {
        if (values[i] > best_value) {
            best_value = values[i];
            best_index = i;
        }
    }

    return best_index;
}

/* 함수 설명: float 값을 USB 로그에 쓰기 좋은 고정 소수점 문자열로 변환합니다. */
static void BreathAI_FormatScaled(char *buffer, size_t size, float value)
{
    int32_t scaled;
    int32_t whole;
    int32_t frac;

    if (buffer == NULL || size == 0U) {
        return;
    }

    scaled = (int32_t)((value * 1000000.0f) + ((value >= 0.0f) ? 0.5f : -0.5f));
    whole = scaled / 1000000;
    frac = scaled % 1000000;
    if (frac < 0) {
        frac = -frac;
    }

    (void)snprintf(buffer, size, "%ld.%06ld", (long)whole, (long)frac);
}

/* 함수 설명: NULL 종료 문자열을 USB CDC로 전송합니다. */
static void BreathAI_SendText(const char *text)
{
    const uint32_t timeout_ms = 20U;

    if (text == NULL) {
        return;
    }

    while (*text != '\0') {
        const size_t remaining = strlen(text);
        const uint16_t chunk = (uint16_t)((remaining > 128U) ? 128U : remaining);
        const uint32_t start_tick = HAL_GetTick();

        while (CDC_Transmit_FS((uint8_t *)text, chunk) == USBD_BUSY) {
            if ((HAL_GetTick() - start_tick) > timeout_ms) {
                return;
            }
        }

        text += chunk;
    }
}

/* 함수 설명: STM32Cube.AI 네트워크 핸들, 활성화 버퍼, 입출력 텐서를 초기화합니다. */
breath_ai_status_t BreathAI_Init(void)
{
    const ai_handle activations[] = {
        AI_HANDLE_PTR(s_breath_ai_activations),
    };
    ai_error error;

    if (s_breath_ai_network != AI_HANDLE_NULL) {
        return BREATH_AI_STATUS_OK;
    }

    error = ai_breath_mlp_create_and_init(&s_breath_ai_network, activations, NULL);
    if (error.type != AI_ERROR_NONE) {
        s_breath_ai_network = AI_HANDLE_NULL;
        return BREATH_AI_STATUS_CREATE_FAILED;
    }

    return BREATH_AI_STATUS_OK;
}

/* 함수 설명: 정규화된 30개 특징 벡터를 모델에 넣고 5클래스 확률을 출력합니다. */
breath_ai_status_t BreathAI_Predict(
    const float features[BREATH_AI_FEATURE_COUNT],
    float probabilities[BREATH_AI_LABEL_COUNT])
{
    ai_buffer *input;
    ai_buffer *output;
    ai_i32 batches;

    if ((features == NULL) || (probabilities == NULL)) {
        return BREATH_AI_STATUS_BAD_ARGUMENT;
    }

    if (BreathAI_Init() != BREATH_AI_STATUS_OK) {
        return BREATH_AI_STATUS_CREATE_FAILED;
    }

    memcpy(s_breath_ai_input, features, sizeof(s_breath_ai_input));
    memset(s_breath_ai_output, 0, sizeof(s_breath_ai_output));

    input = ai_breath_mlp_inputs_get(s_breath_ai_network, NULL);
    output = ai_breath_mlp_outputs_get(s_breath_ai_network, NULL);
    if ((input == NULL) || (output == NULL)) {
        return BREATH_AI_STATUS_RUN_FAILED;
    }

    input[0].data = AI_HANDLE_PTR(s_breath_ai_input);
    output[0].data = AI_HANDLE_PTR(s_breath_ai_output);

    batches = ai_breath_mlp_run(s_breath_ai_network, input, output);
    if (batches != 1) {
        return BREATH_AI_STATUS_RUN_FAILED;
    }

    memcpy(probabilities, s_breath_ai_output, sizeof(s_breath_ai_output));
    return BREATH_AI_STATUS_OK;
}

/* 함수 설명: int16 PCM 프레임에서 특징을 추출한 뒤 같은 모델 예측 경로로 전달합니다. */
breath_ai_status_t BreathAI_PredictPcmI16(
    const int16_t pcm[BREATH_AI_FRAME_SIZE],
    float probabilities[BREATH_AI_LABEL_COUNT])
{
    float features[BREATH_AI_FEATURE_COUNT];
    breath_feature_status_t feature_status;

    if ((pcm == NULL) || (probabilities == NULL)) {
        return BREATH_AI_STATUS_BAD_ARGUMENT;
    }

    feature_status = breath_features_extract_from_pcm_i16(
        &s_breath_ai_feature_scratch,
        pcm,
        features);
    if (feature_status != BREATH_FEATURE_STATUS_OK) {
        return BREATH_AI_STATUS_RUN_FAILED;
    }

    return BreathAI_Predict(features, probabilities);
}

breath_ai_status_t BreathAI_ProcessPcmI16Stream(
    const int16_t *pcm,
    uint32_t sample_count,
    float probabilities[BREATH_AI_LABEL_COUNT],
    uint8_t *prediction_ready)
{
    float features[BREATH_AI_FEATURE_COUNT];
    breath_feature_status_t feature_status;

    if ((pcm == NULL) || (probabilities == NULL) || (prediction_ready == NULL)) {
        return BREATH_AI_STATUS_BAD_ARGUMENT;
    }

    *prediction_ready = 0U;
    feature_status = breath_features_process_pcm_i16_stream(
        &s_breath_ai_feature_scratch,
        pcm,
        sample_count,
        features,
        prediction_ready);
    if (feature_status != BREATH_FEATURE_STATUS_OK) {
        return BREATH_AI_STATUS_RUN_FAILED;
    }

    if (*prediction_ready == 0U) {
        return BREATH_AI_STATUS_OK;
    }

    return BreathAI_Predict(features, probabilities);
}

void BreathAI_ResetFeatureStream(void)
{
    breath_features_reset_filter_state(&s_breath_ai_feature_scratch);
}

/* 함수 설명: 모델 확률 배열에서 가장 큰 값을 가진 클래스 인덱스를 선택합니다. */
uint32_t BreathAI_ArgmaxProbabilities(
    const float probabilities[BREATH_AI_LABEL_COUNT])
{
    if (probabilities == NULL) {
        return 0U;
    }

    return BreathAI_Argmax(probabilities, BREATH_AI_LABEL_COUNT);
}

/* 함수 설명: PC 명령으로 제어되는 실시간 AI 추론 활성화 플래그를 설정합니다. */
void BreathAI_SetLiveInferenceEnabled(uint32_t enabled)
{
    breath_ai_live_inference_enabled = (enabled != 0U) ? 1U : 0U;
    if (breath_ai_live_inference_enabled == 0U) {
        BreathAI_ResetFeatureStream();
    }
}

/* 함수 설명: 현재 실시간 AI 추론이 켜져 있는지 확인합니다. */
uint32_t BreathAI_IsLiveInferenceEnabled(void)
{
    return breath_ai_live_inference_enabled;
}

/* 함수 설명: golden vector를 이용해 STM 모델 출력이 기준 결과와 맞는지 검사합니다. */
breath_ai_status_t BreathAI_RunGoldenModelSelfTest(
    breath_ai_self_test_result_t *result)
{
    float probabilities[BREATH_AI_LABEL_COUNT];

    if (result == NULL) {
        return BREATH_AI_STATUS_BAD_ARGUMENT;
    }

    BreathAI_ResetSelfTestResult(result);

    for (uint32_t vector = 0U; vector < BREATH_GOLDEN_VECTOR_COUNT; ++vector) {
        breath_ai_status_t status;
        uint32_t predicted_label;
        uint8_t vector_passed = 1U;

        status = BreathAI_Predict(BREATH_GOLDEN_FEATURES[vector], probabilities);
        if (status != BREATH_AI_STATUS_OK) {
            result->passed = 0U;
            return status;
        }

        for (uint32_t output = 0U; output < BREATH_AI_LABEL_COUNT; ++output) {
            const float error = fabsf(probabilities[output] - BREATH_GOLDEN_MLP_PROBS[vector][output]);
            if (error > result->max_model_abs_error) {
                result->max_model_abs_error = error;
                result->worst_model_vector = vector;
                result->worst_model_output = output;
            }
            if (error > BREATH_AI_GOLDEN_MODEL_TOLERANCE) {
                vector_passed = 0U;
            }
        }

        predicted_label = BreathAI_Argmax(probabilities, BREATH_AI_LABEL_COUNT);
        if (predicted_label != BREATH_GOLDEN_MLP_PRED_LABEL_INDEX[vector]) {
            vector_passed = 0U;
            ++result->predicted_label_mismatches;
        }

        ++result->checked_vectors;
        if (vector_passed != 0U) {
            ++result->passed_vectors;
        }
    }

    if ((result->passed_vectors != result->checked_vectors) ||
        (result->predicted_label_mismatches != 0U)) {
        result->passed = 0U;
        return BREATH_AI_STATUS_MISMATCH;
    }

    return BREATH_AI_STATUS_OK;
}

/* 함수 설명: 부팅 직후 모델 self-test를 수행하고 USB CDC 로그로 결과를 전송합니다. */
void BreathAI_RunBootSelfTest(void)
{
    breath_ai_self_test_result_t result;
    breath_ai_status_t status;
    char line[160];
    char max_error_text[24];

    HAL_Delay(1000U);
    BreathAI_SendText("\r\nBREATH_AI self-test start\r\n");

    status = BreathAI_RunGoldenModelSelfTest(&result);

    breath_ai_boot_status = (uint32_t)status;
    breath_ai_boot_checked_vectors = result.checked_vectors;
    breath_ai_boot_passed_vectors = result.passed_vectors;
    breath_ai_boot_label_mismatches = result.predicted_label_mismatches;
    breath_ai_boot_max_model_abs_error = result.max_model_abs_error;

    BreathAI_FormatScaled(max_error_text, sizeof(max_error_text), result.max_model_abs_error);
    (void)snprintf(
        line,
        sizeof(line),
        "BREATH_AI self-test %s checked=%lu passed=%lu label_mismatch=%lu max_prob_error=%s worst=gv_%03lu/out%lu\r\n",
        (status == BREATH_AI_STATUS_OK) ? "PASS" : "FAIL",
        (unsigned long)result.checked_vectors,
        (unsigned long)result.passed_vectors,
        (unsigned long)result.predicted_label_mismatches,
        max_error_text,
        (unsigned long)result.worst_model_vector,
        (unsigned long)result.worst_model_output);
    BreathAI_SendText(line);

    BreathAI_SendText("BREATH_AI live ADC inference packets enabled; commands: AI ON / AI OFF\r\n");
}
