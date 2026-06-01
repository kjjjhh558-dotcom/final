/* 파일 설명: MAX9814 PCM 프레임에 causal 필터를 적용하고, TinyML 모델 입력용 30개 특징을 C 코드에서 계산합니다. */

#include "breath_features.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "breath_dsp_tables.h"
#include "breath_fft_backend_config.h"

#if BREATH_FFT_BACKEND == BREATH_FFT_BACKEND_CMSIS_DSP
#ifndef ARM_MATH_CM4
#define ARM_MATH_CM4
#endif
#include "arm_math.h"
#endif

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#if BREATH_DSP_SOS_SECTIONS != BREATH_FEATURES_SOS_SECTIONS
#error "SOS section count mismatch between breath_features.h and breath_dsp_tables.h"
#endif

#if BREATH_DSP_FFT_BINS != BREATH_FEATURES_FFT_BINS
#error "FFT bin count mismatch between breath_features.h and breath_dsp_tables.h"
#endif

static uint8_t s_runtime_tables_ready = 0U;
static float s_mfcc_dct[BREATH_AI_NUM_MFCC][BREATH_AI_NUM_MELS];

#if BREATH_FFT_BACKEND == BREATH_FFT_BACKEND_CMSIS_DSP
static arm_rfft_fast_instance_f32 s_cmsis_rfft;
static uint8_t s_cmsis_rfft_ready = 0U;
#endif

#define BREATH_DELTA_DENOMINATOR 10.0f

/* Runtime tables for MFCC DCT are initialized once and reused. */
static void breath_init_runtime_tables(void)
{
    if (s_runtime_tables_ready != 0U) {
        return;
    }

    const float n_mels = (float)BREATH_AI_NUM_MELS;
    for (size_t coeff = 0; coeff < BREATH_AI_NUM_MFCC; ++coeff) {
        const float scale = (coeff == 0U) ? sqrtf(1.0f / n_mels) : sqrtf(2.0f / n_mels);
        for (size_t mel = 0; mel < BREATH_AI_NUM_MELS; ++mel) {
            const float angle =
                (float)M_PI * (float)coeff * (2.0f * (float)mel + 1.0f) / (2.0f * n_mels);
            s_mfcc_dct[coeff][mel] = scale * cosf(angle);
        }
    }

#if BREATH_FFT_BACKEND == BREATH_FFT_BACKEND_CMSIS_DSP
    if (arm_rfft_fast_init_4096_f32(&s_cmsis_rfft) == ARM_MATH_SUCCESS) {
        s_cmsis_rfft_ready = 1U;
    }
#endif

    s_runtime_tables_ready = 1U;
}

/* 함수 설명: FFT bin 번호를 실제 주파수 Hz 값으로 변환합니다. */
static uint32_t breath_reverse_bits(uint32_t value, uint32_t bits)
{
    uint32_t reversed = 0U;
    for (uint32_t i = 0U; i < bits; ++i) {
        reversed = (reversed << 1U) | (value & 1U);
        value >>= 1U;
    }
    return reversed;
}

static float breath_bin_freq(size_t bin)
{
    return ((float)bin * (float)BREATH_AI_SAMPLE_RATE) / (float)BREATH_AI_FFT_SIZE;
}

/* 함수 설명: 파워 스펙트럼에서 지정한 주파수 대역의 평균 에너지를 계산합니다. */
static float breath_band_energy(const float *power, float low_hz, float high_hz)
{
    float energy = 0.0f;

    for (size_t bin = 0; bin < BREATH_FEATURES_FFT_BINS; ++bin) {
        const float freq = breath_bin_freq(bin);
        if ((freq >= low_hz) && (freq < high_hz)) {
            energy += power[bin];
        }
    }

    return energy;
}

/* 함수 설명: 프레임 내 신호 부호가 바뀌는 비율을 계산해 시간영역 특징으로 사용합니다. */
static float breath_zero_crossing_rate(const float frame[BREATH_AI_FRAME_SIZE])
{
    uint32_t crossings = 0U;

    for (size_t i = 1; i < BREATH_AI_FRAME_SIZE; ++i) {
        const uint8_t previous_negative = signbit(frame[i - 1U]) ? 1U : 0U;
        const uint8_t current_negative = signbit(frame[i]) ? 1U : 0U;
        if (previous_negative != current_negative) {
            ++crossings;
        }
    }

    return (float)crossings / (float)(BREATH_AI_FRAME_SIZE - 1U);
}

static float breath_filter_sample_i16(breath_feature_scratch_t *scratch, int16_t pcm)
{
    float x = (float)pcm / 32768.0f;

    for (size_t section = 0; section < BREATH_FEATURES_SOS_SECTIONS; ++section) {
        const float b0 = BREATH_DSP_FILTER_SOS[section][0];
        const float b1 = BREATH_DSP_FILTER_SOS[section][1];
        const float b2 = BREATH_DSP_FILTER_SOS[section][2];
        const float a0 = BREATH_DSP_FILTER_SOS[section][3];
        const float a1 = BREATH_DSP_FILTER_SOS[section][4];
        const float a2 = BREATH_DSP_FILTER_SOS[section][5];
        const float z0 = scratch->sos_state[section][0];
        const float z1 = scratch->sos_state[section][1];
        const float y = ((b0 * x) + z0) / a0;

        scratch->sos_state[section][0] = (b1 * x) - (a1 * y) + z1;
        scratch->sos_state[section][1] = (b2 * x) - (a2 * y);
        x = y;
    }

    return x;
}

/* Convert a filtered frame into a power spectrum with an in-place radix-2 FFT. */
static void breath_compute_power_spectrum_internal(
    breath_feature_scratch_t *scratch,
    const float frame[BREATH_AI_FRAME_SIZE],
    float power[BREATH_FEATURES_FFT_BINS])
{
    uint32_t fft_bits = 0U;

    while ((1U << fft_bits) < BREATH_AI_FFT_SIZE) {
        fft_bits++;
    }

    for (uint32_t n = 0U; n < BREATH_AI_FFT_SIZE; ++n) {
        const uint32_t reversed = breath_reverse_bits(n, fft_bits);
        scratch->fft_real[reversed] =
            (n < BREATH_AI_FRAME_SIZE) ? (frame[n] * BREATH_DSP_HANN_WINDOW[n]) : 0.0f;
        scratch->fft_imag[reversed] = 0.0f;
    }

    for (uint32_t length = 2U; length <= BREATH_AI_FFT_SIZE; length <<= 1U) {
        const uint32_t half_length = length >> 1U;
        const float angle_step = (float)(-2.0 * M_PI) / (float)length;
        const float w_step_real = cosf(angle_step);
        const float w_step_imag = sinf(angle_step);

        for (uint32_t offset = 0U; offset < BREATH_AI_FFT_SIZE; offset += length) {
            float w_real = 1.0f;
            float w_imag = 0.0f;

            for (uint32_t j = 0U; j < half_length; ++j) {
                const uint32_t even = offset + j;
                const uint32_t odd = even + half_length;
                const float odd_real = scratch->fft_real[odd];
                const float odd_imag = scratch->fft_imag[odd];
                const float t_real = (w_real * odd_real) - (w_imag * odd_imag);
                const float t_imag = (w_real * odd_imag) + (w_imag * odd_real);
                const float even_real = scratch->fft_real[even];
                const float even_imag = scratch->fft_imag[even];
                const float next_w_real = (w_real * w_step_real) - (w_imag * w_step_imag);
                const float next_w_imag = (w_real * w_step_imag) + (w_imag * w_step_real);

                scratch->fft_real[even] = even_real + t_real;
                scratch->fft_imag[even] = even_imag + t_imag;
                scratch->fft_real[odd] = even_real - t_real;
                scratch->fft_imag[odd] = even_imag - t_imag;

                w_real = next_w_real;
                w_imag = next_w_imag;
            }
        }
    }

    for (uint32_t bin = 0U; bin < BREATH_FEATURES_FFT_BINS; ++bin) {
        const float real = scratch->fft_real[bin];
        const float imag = scratch->fft_imag[bin];
        power[bin] = (real * real) + (imag * imag);
    }
}

#if BREATH_FFT_BACKEND == BREATH_FFT_BACKEND_CMSIS_DSP
/* CMSIS-DSP RFFT backend. Output packing is:
 * out[0] = DC real, out[1] = Nyquist real, out[2*k] / out[2*k+1] = bin k.
 */
static void breath_compute_power_spectrum_cmsis(
    breath_feature_scratch_t *scratch,
    const float frame[BREATH_AI_FRAME_SIZE],
    float power[BREATH_FEATURES_FFT_BINS])
{
    breath_init_runtime_tables();

    for (uint32_t n = 0U; n < BREATH_AI_FFT_SIZE; ++n) {
        scratch->fft_real[n] =
            (n < BREATH_AI_FRAME_SIZE) ? (frame[n] * BREATH_DSP_HANN_WINDOW[n]) : 0.0f;
    }

    arm_rfft_fast_f32(&s_cmsis_rfft, scratch->fft_real, scratch->fft_imag, 0U);

    power[0] = scratch->fft_imag[0] * scratch->fft_imag[0];
    for (uint32_t bin = 1U; bin < (BREATH_AI_FFT_SIZE / 2U); ++bin) {
        const float real = scratch->fft_imag[2U * bin];
        const float imag = scratch->fft_imag[(2U * bin) + 1U];
        power[bin] = (real * real) + (imag * imag);
    }
    power[BREATH_AI_FFT_SIZE / 2U] = scratch->fft_imag[1] * scratch->fft_imag[1];
}
#endif

static void breath_compute_power_spectrum(
    breath_feature_scratch_t *scratch,
    const float frame[BREATH_AI_FRAME_SIZE],
    float power[BREATH_FEATURES_FFT_BINS])
{
#if BREATH_FFT_BACKEND == BREATH_FFT_BACKEND_CMSIS_DSP
    breath_init_runtime_tables();
    if (s_cmsis_rfft_ready != 0U) {
        breath_compute_power_spectrum_cmsis(scratch, frame, power);
        return;
    }
#endif

    breath_compute_power_spectrum_internal(scratch, frame, power);
}

/* 함수 설명: mel filterbank 에너지에서 MFCC 계수를 계산합니다. */
static void breath_compute_mfcc(
    breath_feature_scratch_t *scratch,
    float mfcc[BREATH_AI_NUM_MFCC])
{
    breath_init_runtime_tables();

    for (size_t mel = 0; mel < BREATH_AI_NUM_MELS; ++mel) {
        float energy = 0.0f;
        for (size_t bin = 0; bin < BREATH_FEATURES_FFT_BINS; ++bin) {
            energy += BREATH_DSP_MEL_FILTERBANK[mel][bin] * scratch->power_spectrum[bin];
        }
        scratch->mel_energy[mel] = energy;
        scratch->log_mel_energy[mel] = logf(energy + BREATH_AI_EPS);
    }

    for (size_t coeff = 0; coeff < BREATH_AI_NUM_MFCC; ++coeff) {
        float sum = 0.0f;
        for (size_t mel = 0; mel < BREATH_AI_NUM_MELS; ++mel) {
            sum += scratch->log_mel_energy[mel] * s_mfcc_dct[coeff][mel];
        }
        mfcc[coeff] = sum;
    }
}

/* 함수 설명: causal IIR 필터의 내부 지연 상태를 0으로 초기화합니다. */
void breath_features_reset_filter_state(breath_feature_scratch_t *scratch)
{
    if (scratch == NULL) {
        return;
    }

    memset(scratch, 0, sizeof(*scratch));
    scratch->stream_next_frame_end_sample = BREATH_AI_FRAME_SIZE;
}

/* 함수 설명: Python golden vector 등 외부 기준 상태를 STM 필터 scratch에 주입합니다. */
breath_feature_status_t breath_features_set_filter_state(
    breath_feature_scratch_t *scratch,
    const float state[BREATH_FEATURES_SOS_SECTIONS][2])
{
    if ((scratch == NULL) || (state == NULL)) {
        return BREATH_FEATURE_STATUS_NULL_ARGUMENT;
    }

    memcpy(scratch->sos_state, state, sizeof(scratch->sos_state));
    return BREATH_FEATURE_STATUS_OK;
}

/* 함수 설명: 현재 causal IIR 필터의 내부 상태를 외부 버퍼로 복사합니다. */
breath_feature_status_t breath_features_get_filter_state(
    const breath_feature_scratch_t *scratch,
    float state[BREATH_FEATURES_SOS_SECTIONS][2])
{
    if ((scratch == NULL) || (state == NULL)) {
        return BREATH_FEATURE_STATUS_NULL_ARGUMENT;
    }

    memcpy(state, scratch->sos_state, sizeof(scratch->sos_state));
    return BREATH_FEATURE_STATUS_OK;
}

/* 함수 설명: int16 PCM 입력을 float로 변환하고 SOS causal 필터를 적용합니다. */
breath_feature_status_t breath_features_filter_pcm_i16(
    breath_feature_scratch_t *scratch,
    const int16_t pcm[BREATH_AI_FRAME_SIZE],
    float filtered[BREATH_AI_FRAME_SIZE])
{
    if ((scratch == NULL) || (pcm == NULL) || (filtered == NULL)) {
        return BREATH_FEATURE_STATUS_NULL_ARGUMENT;
    }

    for (size_t n = 0; n < BREATH_AI_FRAME_SIZE; ++n) {
        filtered[n] = breath_filter_sample_i16(scratch, pcm[n]);
    }

    return BREATH_FEATURE_STATUS_OK;
}

/* 함수 설명: 이미 필터링된 프레임에서 모델 입력용 특징 벡터를 계산합니다. */
breath_feature_status_t breath_features_extract_from_filtered_frame(
    breath_feature_scratch_t *scratch,
    const float filtered[BREATH_AI_FRAME_SIZE],
    float features[BREATH_AI_FEATURE_COUNT])
{
    if ((scratch == NULL) || (filtered == NULL) || (features == NULL)) {
        return BREATH_FEATURE_STATUS_NULL_ARGUMENT;
    }

    float sum_square = 0.0f;
    for (size_t i = 0; i < BREATH_AI_FRAME_SIZE; ++i) {
        sum_square += filtered[i] * filtered[i];
    }

    const float rms = sqrtf((sum_square / (float)BREATH_AI_FRAME_SIZE) + BREATH_AI_EPS);
    const float log_rms = logf(rms + BREATH_AI_EPS);
    const float zcr = breath_zero_crossing_rate(filtered);

    breath_compute_power_spectrum(scratch, filtered, scratch->power_spectrum);

    float power_sum = 0.0f;
    float weighted_freq_sum = 0.0f;
    float log_power_sum = 0.0f;

    for (size_t bin = 0; bin < BREATH_FEATURES_FFT_BINS; ++bin) {
        const float power = scratch->power_spectrum[bin];
        const float freq = breath_bin_freq(bin);
        power_sum += power;
        weighted_freq_sum += freq * power;
        log_power_sum += logf(power + BREATH_AI_EPS);
    }

    const float total_energy = power_sum + BREATH_AI_EPS;
    const float centroid = weighted_freq_sum / total_energy;

    float bandwidth_num = 0.0f;
    for (size_t bin = 0; bin < BREATH_FEATURES_FFT_BINS; ++bin) {
        const float freq_delta = breath_bin_freq(bin) - centroid;
        bandwidth_num += (freq_delta * freq_delta) * scratch->power_spectrum[bin];
    }
    const float bandwidth = sqrtf(bandwidth_num / total_energy);

    const float mean_power = power_sum / (float)BREATH_FEATURES_FFT_BINS;
    const float mean_log_power = log_power_sum / (float)BREATH_FEATURES_FFT_BINS;
    const float flatness = expf(mean_log_power) / (mean_power + BREATH_AI_EPS);

    const float rolloff_threshold = BREATH_AI_ROLLOFF_RATIO * total_energy;
    float cumulative = 0.0f;
    size_t rolloff_index = BREATH_FEATURES_FFT_BINS - 1U;
    size_t dominant_index = 0U;
    float dominant_power = scratch->power_spectrum[0];

    for (size_t bin = 0; bin < BREATH_FEATURES_FFT_BINS; ++bin) {
        cumulative += scratch->power_spectrum[bin];
        if ((rolloff_index == (BREATH_FEATURES_FFT_BINS - 1U)) && (cumulative >= rolloff_threshold)) {
            rolloff_index = bin;
        }

        if (scratch->power_spectrum[bin] > dominant_power) {
            dominant_power = scratch->power_spectrum[bin];
            dominant_index = bin;
        }
    }

    const float energy_50_300 = breath_band_energy(scratch->power_spectrum, 50.0f, 300.0f);
    const float energy_300_800 = breath_band_energy(scratch->power_spectrum, 300.0f, 800.0f);
    const float energy_800_2000 = breath_band_energy(scratch->power_spectrum, 800.0f, 2000.0f);
    const float energy_2000_4000 = breath_band_energy(scratch->power_spectrum, 2000.0f, 4000.0f);

    float mfcc[BREATH_AI_NUM_MFCC];
    breath_compute_mfcc(scratch, mfcc);

    features[0] = rms;
    features[1] = log_rms;
    features[2] = zcr;
    features[3] = centroid;
    features[4] = bandwidth;
    features[5] = flatness;
    features[6] = breath_bin_freq(rolloff_index);
    features[7] = breath_bin_freq(dominant_index);
    features[8] = total_energy;
    features[9] = energy_50_300;
    features[10] = energy_300_800;
    features[11] = energy_800_2000;
    features[12] = energy_2000_4000;
    features[13] = energy_50_300 / total_energy;
    features[14] = energy_300_800 / total_energy;
    features[15] = energy_800_2000 / total_energy;
    features[16] = energy_2000_4000 / total_energy;

    for (size_t i = 0; i < BREATH_AI_NUM_MFCC; ++i) {
        features[17U + i] = mfcc[i];
    }

    for (size_t i = 17U + BREATH_AI_NUM_MFCC; i < BREATH_AI_FEATURE_COUNT; ++i) {
        features[i] = 0.0f;
    }

    return BREATH_FEATURE_STATUS_OK;
}

/* 함수 설명: PCM 입력 필터링과 특징 추출을 한 번에 수행합니다. */
breath_feature_status_t breath_features_extract_from_pcm_i16(
    breath_feature_scratch_t *scratch,
    const int16_t pcm[BREATH_AI_FRAME_SIZE],
    float features[BREATH_AI_FEATURE_COUNT])
{
    breath_feature_status_t status;

    if ((scratch == NULL) || (pcm == NULL) || (features == NULL)) {
        return BREATH_FEATURE_STATUS_NULL_ARGUMENT;
    }

    status = breath_features_filter_pcm_i16(scratch, pcm, scratch->filtered_frame);
    if (status != BREATH_FEATURE_STATUS_OK) {
        return status;
    }

    return breath_features_extract_from_filtered_frame(scratch, scratch->filtered_frame, features);
}

static uint32_t breath_history_index_from_oldest(
    const breath_feature_scratch_t *scratch,
    uint32_t offset_from_oldest)
{
    uint32_t oldest;

    if (scratch->feature_history_count < BREATH_FEATURES_HISTORY_COUNT) {
        oldest = 0U;
    } else {
        oldest = scratch->feature_history_write;
    }

    return (oldest + offset_from_oldest) % BREATH_FEATURES_HISTORY_COUNT;
}

static void breath_copy_filtered_ring_to_frame(breath_feature_scratch_t *scratch)
{
    uint32_t start = 0U;

    if (scratch->filtered_ring_count >= BREATH_AI_FRAME_SIZE) {
        start = scratch->filtered_ring_write;
    }

    for (uint32_t i = 0U; i < BREATH_AI_FRAME_SIZE; ++i) {
        scratch->filtered_frame[i] = scratch->filtered_ring[(start + i) % BREATH_AI_FRAME_SIZE];
    }
}

static void breath_push_feature_history(
    breath_feature_scratch_t *scratch,
    const float features[BREATH_AI_FEATURE_COUNT])
{
    const uint32_t index = scratch->feature_history_write;

    for (uint32_t i = 0U; i < BREATH_FEATURES_BASE_COUNT; ++i) {
        scratch->base_history[index][i] = features[i];
    }

    for (uint32_t i = 0U; i < BREATH_AI_NUM_MFCC; ++i) {
        scratch->mfcc_history[index][i] = features[BREATH_FEATURES_BASE_COUNT + i];
    }

    scratch->feature_history_write = (scratch->feature_history_write + 1U) % BREATH_FEATURES_HISTORY_COUNT;
    if (scratch->feature_history_count < BREATH_FEATURES_HISTORY_COUNT) {
        scratch->feature_history_count++;
    }
}

static void breath_compute_delta_at_history_offset(
    const breath_feature_scratch_t *scratch,
    uint32_t center_offset,
    float delta[BREATH_AI_NUM_MFCC])
{
    const uint32_t minus_2 = breath_history_index_from_oldest(scratch, center_offset - 2U);
    const uint32_t minus_1 = breath_history_index_from_oldest(scratch, center_offset - 1U);
    const uint32_t plus_1 = breath_history_index_from_oldest(scratch, center_offset + 1U);
    const uint32_t plus_2 = breath_history_index_from_oldest(scratch, center_offset + 2U);

    for (uint32_t i = 0U; i < BREATH_AI_NUM_MFCC; ++i) {
        delta[i] =
            ((scratch->mfcc_history[plus_1][i] - scratch->mfcc_history[minus_1][i]) +
             (2.0f * (scratch->mfcc_history[plus_2][i] - scratch->mfcc_history[minus_2][i]))) /
            BREATH_DELTA_DENOMINATOR;
    }
}

static void breath_build_full56_from_history(
    const breath_feature_scratch_t *scratch,
    float features[BREATH_AI_FEATURE_COUNT])
{
    const uint32_t center_offset = BREATH_FEATURES_DELTA_LOOKAHEAD;
    const uint32_t center_index = breath_history_index_from_oldest(scratch, center_offset);
    float delta_center[BREATH_AI_NUM_MFCC];
    float delta_m2[BREATH_AI_NUM_MFCC];
    float delta_m1[BREATH_AI_NUM_MFCC];
    float delta_p1[BREATH_AI_NUM_MFCC];
    float delta_p2[BREATH_AI_NUM_MFCC];

    for (uint32_t i = 0U; i < BREATH_FEATURES_BASE_COUNT; ++i) {
        features[i] = scratch->base_history[center_index][i];
    }

    for (uint32_t i = 0U; i < BREATH_AI_NUM_MFCC; ++i) {
        features[BREATH_FEATURES_BASE_COUNT + i] = scratch->mfcc_history[center_index][i];
    }

    breath_compute_delta_at_history_offset(scratch, center_offset, delta_center);
    breath_compute_delta_at_history_offset(scratch, center_offset - 2U, delta_m2);
    breath_compute_delta_at_history_offset(scratch, center_offset - 1U, delta_m1);
    breath_compute_delta_at_history_offset(scratch, center_offset + 1U, delta_p1);
    breath_compute_delta_at_history_offset(scratch, center_offset + 2U, delta_p2);

    for (uint32_t i = 0U; i < BREATH_AI_NUM_MFCC; ++i) {
        const uint32_t delta_index = BREATH_FEATURES_BASE_COUNT + BREATH_AI_NUM_MFCC + i;
        const uint32_t delta2_index = delta_index + BREATH_AI_NUM_MFCC;
        features[delta_index] = delta_center[i];
        features[delta2_index] =
            ((delta_p1[i] - delta_m1[i]) + (2.0f * (delta_p2[i] - delta_m2[i]))) /
            BREATH_DELTA_DENOMINATOR;
    }
}

breath_feature_status_t breath_features_process_pcm_i16_stream(
    breath_feature_scratch_t *scratch,
    const int16_t *pcm,
    uint32_t sample_count,
    float features[BREATH_AI_FEATURE_COUNT],
    uint8_t *feature_ready)
{
    if ((scratch == NULL) || (pcm == NULL) || (features == NULL) || (feature_ready == NULL)) {
        return BREATH_FEATURE_STATUS_NULL_ARGUMENT;
    }

    *feature_ready = 0U;
    if (scratch->stream_next_frame_end_sample == 0U) {
        scratch->stream_next_frame_end_sample = BREATH_AI_FRAME_SIZE;
    }

    for (uint32_t i = 0U; i < sample_count; ++i) {
        const float filtered = breath_filter_sample_i16(scratch, pcm[i]);

        scratch->filtered_ring[scratch->filtered_ring_write] = filtered;
        scratch->filtered_ring_write = (scratch->filtered_ring_write + 1U) % BREATH_AI_FRAME_SIZE;
        if (scratch->filtered_ring_count < BREATH_AI_FRAME_SIZE) {
            scratch->filtered_ring_count++;
        }

        scratch->stream_total_samples++;
        if (scratch->stream_total_samples >= scratch->stream_next_frame_end_sample) {
            float static_features[BREATH_AI_FEATURE_COUNT];
            breath_feature_status_t status;

            breath_copy_filtered_ring_to_frame(scratch);
            status = breath_features_extract_from_filtered_frame(
                scratch,
                scratch->filtered_frame,
                static_features);
            if (status != BREATH_FEATURE_STATUS_OK) {
                return status;
            }

            breath_push_feature_history(scratch, static_features);
            scratch->stream_next_frame_end_sample += BREATH_AI_HOP_SIZE;

            if (scratch->feature_history_count >= BREATH_FEATURES_HISTORY_COUNT) {
#if BREATH_AI_FEATURE_COUNT >= 56
                breath_build_full56_from_history(scratch, features);
#else
                memcpy(features, static_features, sizeof(float) * BREATH_AI_FEATURE_COUNT);
#endif
                *feature_ready = 1U;
            }
        }
    }

    return BREATH_FEATURE_STATUS_OK;
}

/* 함수 설명: 학습 때 저장한 평균과 표준편차로 특징 벡터를 표준화합니다. */
void breath_features_normalize(
    const float features[BREATH_AI_FEATURE_COUNT],
    float normalized[BREATH_AI_FEATURE_COUNT])
{
    if ((features == NULL) || (normalized == NULL)) {
        return;
    }

    for (size_t i = 0; i < BREATH_AI_FEATURE_COUNT; ++i) {
        normalized[i] = (features[i] - BREATH_AI_NORM_MEAN[i]) * BREATH_AI_NORM_INV_STD[i];
    }
}

/* 함수 설명: 두 float 배열 사이의 최대 절대 오차를 계산합니다. */
float breath_features_max_abs_error(
    const float *actual,
    const float *expected,
    size_t count)
{
    float max_error = 0.0f;

    if ((actual == NULL) || (expected == NULL)) {
        return INFINITY;
    }

    for (size_t i = 0; i < count; ++i) {
        const float error = fabsf(actual[i] - expected[i]);
        if (error > max_error) {
            max_error = error;
        }
    }

    return max_error;
}
