/* 파일 설명: STM32 펌웨어와 검증 코드가 공통으로 사용하는 causal 필터와 30개 특징 추출 API를 선언합니다. */

/* Active full56 builds use streaming SOS filtering, a 4096-point FFT spectrum,
 * and MFCC delta history. Preserved 30-feature fallback assets use the same
 * API shape with a smaller BREATH_AI_FEATURE_COUNT.
 */
#ifndef BREATH_FEATURES_H
#define BREATH_FEATURES_H

#include <stddef.h>
#include <stdint.h>

#include "breath_ai_config.h"

#ifdef __cplusplus
extern "C" {
#endif

#define BREATH_FEATURES_SOS_SECTIONS 4
#define BREATH_FEATURES_FFT_BINS ((BREATH_AI_FFT_SIZE / 2) + 1)
#define BREATH_FEATURES_BASE_COUNT 17
#define BREATH_FEATURES_DELTA_WIDTH 2
#define BREATH_FEATURES_DELTA_LOOKAHEAD (BREATH_FEATURES_DELTA_WIDTH * 2)
#define BREATH_FEATURES_HISTORY_COUNT ((BREATH_FEATURES_DELTA_LOOKAHEAD * 2) + 1)

typedef enum {
    BREATH_FEATURE_STATUS_OK = 0,
    BREATH_FEATURE_STATUS_NULL_ARGUMENT = 1,
    BREATH_FEATURE_STATUS_BAD_INDEX = 2,
    BREATH_FEATURE_STATUS_MISMATCH = 3
} breath_feature_status_t;

typedef struct {
    float sos_state[BREATH_FEATURES_SOS_SECTIONS][2];
    float filtered_frame[BREATH_AI_FRAME_SIZE];
    float power_spectrum[BREATH_FEATURES_FFT_BINS];
    float mel_energy[BREATH_AI_NUM_MELS];
    float log_mel_energy[BREATH_AI_NUM_MELS];
    float fft_real[BREATH_AI_FFT_SIZE];
    float fft_imag[BREATH_AI_FFT_SIZE];
    float filtered_ring[BREATH_AI_FRAME_SIZE];
    float base_history[BREATH_FEATURES_HISTORY_COUNT][BREATH_FEATURES_BASE_COUNT];
    float mfcc_history[BREATH_FEATURES_HISTORY_COUNT][BREATH_AI_NUM_MFCC];
    uint32_t filtered_ring_write;
    uint32_t filtered_ring_count;
    uint32_t stream_total_samples;
    uint32_t stream_next_frame_end_sample;
    uint32_t feature_history_write;
    uint32_t feature_history_count;
} breath_feature_scratch_t;

/* 함수 설명: causal IIR 필터의 내부 지연 상태를 0으로 초기화합니다. */
void breath_features_reset_filter_state(breath_feature_scratch_t *scratch);

/* 함수 설명: Python golden vector 등 외부 기준 상태를 STM 필터 scratch에 주입합니다. */
breath_feature_status_t breath_features_set_filter_state(
    breath_feature_scratch_t *scratch,
    const float state[BREATH_FEATURES_SOS_SECTIONS][2]);

/* 함수 설명: 현재 causal IIR 필터의 내부 상태를 외부 버퍼로 복사합니다. */
breath_feature_status_t breath_features_get_filter_state(
    const breath_feature_scratch_t *scratch,
    float state[BREATH_FEATURES_SOS_SECTIONS][2]);

/* 함수 설명: int16 PCM 입력을 float로 변환하고 SOS causal 필터를 적용합니다. */
breath_feature_status_t breath_features_filter_pcm_i16(
    breath_feature_scratch_t *scratch,
    const int16_t pcm[BREATH_AI_FRAME_SIZE],
    float filtered[BREATH_AI_FRAME_SIZE]);

/* 함수 설명: 이미 필터링된 프레임에서 모델 입력용 특징 벡터를 계산합니다. */
breath_feature_status_t breath_features_extract_from_filtered_frame(
    breath_feature_scratch_t *scratch,
    const float filtered[BREATH_AI_FRAME_SIZE],
    float features[BREATH_AI_FEATURE_COUNT]);

/* 함수 설명: PCM 입력 필터링과 특징 추출을 한 번에 수행합니다. */
breath_feature_status_t breath_features_extract_from_pcm_i16(
    breath_feature_scratch_t *scratch,
    const int16_t pcm[BREATH_AI_FRAME_SIZE],
    float features[BREATH_AI_FEATURE_COUNT]);

/* Push streaming PCM samples through the causal DSP path and emit a delayed
 * 56-feature vector when enough MFCC context exists for delta/delta-delta. */
breath_feature_status_t breath_features_process_pcm_i16_stream(
    breath_feature_scratch_t *scratch,
    const int16_t *pcm,
    uint32_t sample_count,
    float features[BREATH_AI_FEATURE_COUNT],
    uint8_t *feature_ready);

/* 함수 설명: 학습 때 저장한 평균과 표준편차로 특징 벡터를 표준화합니다. */
void breath_features_normalize(
    const float features[BREATH_AI_FEATURE_COUNT],
    float normalized[BREATH_AI_FEATURE_COUNT]);

/* 함수 설명: 두 float 배열 사이의 최대 절대 오차를 계산합니다. */
float breath_features_max_abs_error(
    const float *actual,
    const float *expected,
    size_t count);

#ifdef __cplusplus
}
#endif

#endif /* BREATH_FEATURES_H */
