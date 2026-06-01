/* USER CODE BEGIN Header */
/* 파일 설명: ADC DMA로 마이크 샘플을 수집하고 USB CDC 오디오 패킷과 STM AI 예측 패킷을 PC로 전송하는 메인 펌웨어입니다. */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "usb_device.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "breath_ai_app.h"
#include "max30102_spo2.h"
#include "mic_backend_config.h"
#include "usbd_cdc_if.h"
/* USER CODE END Includes */

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;
DMA_HandleTypeDef hdma_adc1;

I2S_HandleTypeDef hi2s2;
DMA_HandleTypeDef hdma_spi2_rx;
DMA_HandleTypeDef hdma_spi2_tx;

I2C_HandleTypeDef hi2c1;

TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim3;

UART_HandleTypeDef huart1;
UART_HandleTypeDef huart2;
DMA_HandleTypeDef hdma_usart2_tx;

/* USER CODE BEGIN PV */

#define AUDIO_BUFFER_SIZE     8000
#define AUDIO_HALF_SIZE       (AUDIO_BUFFER_SIZE / 2)

#define ADC_DC_OFFSET         1551
#define ADC_TO_PCM_GAIN       16
#define I2S_TO_PCM_GAIN       32

#define PACKET_SAMPLES        512
#define AUDIO_MAGIC           0xAABBCCDD
#define AUDIO_FORMAT_ADC_U16  0U
#define AUDIO_FORMAT_PCM16    1U
#define AI_MAGIC              0xA15A1EAF
#define MAX30102_MAGIC        0xA3025A02U
#define IMU_BRIDGE_MAGIC      0x1A71B2E1U
#define MAX30102_TELEMETRY_PERIOD_MS 100U
#define IMU_BRIDGE_TELEMETRY_PERIOD_MS 200U
#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
#define AI_INFERENCE_BLOCK_STRIDE 8U
#define AI_STABLE_HISTORY_SIZE 12U
#define AI_STABLE_MIN_VOTES   8U
#else
#define AI_INFERENCE_BLOCK_STRIDE 1U
#define AI_STABLE_HISTORY_SIZE 6U
#define AI_STABLE_MIN_VOTES   4U
#endif
#define AI_NOISE_CLASS_INDEX  4U
#define AI_CONFIDENCE_GATE    0.60f
#define AI_STABLE_AVG_CONFIDENCE_GATE 0.60f
#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
#define ADC_ONLY_UNUSED __attribute__((unused))
#else
#define ADC_ONLY_UNUSED
#endif

#define CLASS_LED_PORT        GPIOE
#define CLASS_LED_PULSE_MS    120U
#define LED_MOUTH_EXHALE_PIN  GPIO_PIN_0
#define LED_MOUTH_INHALE_PIN  GPIO_PIN_1
#define LED_NASAL_EXHALE_PIN  GPIO_PIN_2
#define LED_NASAL_INHALE_PIN  GPIO_PIN_3
#define LED_NOISE_PIN         GPIO_PIN_7
#define CLASS_LED_ALL_PINS    (LED_MOUTH_EXHALE_PIN | LED_MOUTH_INHALE_PIN | LED_NASAL_EXHALE_PIN | LED_NASAL_INHALE_PIN | LED_NOISE_PIN)

#define PUMP_ACTION_LED_PORT  GPIOE
#define PUMP_ACTION_LED_PIN   GPIO_PIN_5
#define PUMP_ACTION_LED_WINDOW_MS 2000U
#define PUMP_ACTION_LED_ACTIVE_MS 5000U
#define PUMP_ACTION_LED_MOUTH_PERCENT 50U
#define PUMP_ACTION_LED_MIN_SAMPLES 12U
#define PUMP_ACTION_LED_HISTORY_SIZE 80U

#define SPO2_STATUS_LED_PORT  GPIOE
#define SPO2_STATUS_LED_PIN   GPIO_PIN_8

#define ORAL_AIR_VALVE_PORT   GPIOB
#define ORAL_AIR_VALVE_PIN    GPIO_PIN_0

#define PUMP_PWM_PORT         GPIOA
#define PUMP_PWM_PIN          GPIO_PIN_6
#define PUMP_PWM_CHANNEL      TIM_CHANNEL_1
#define SIDE_PUMP_PWM_PORT    GPIOA
#define SIDE_PUMP_PWM_PIN     GPIO_PIN_7
#define SIDE_PUMP_PWM_CHANNEL TIM_CHANNEL_2
#define SIDE_AIR_VALVE_PORT   GPIOB
#define SIDE_AIR_VALVE_PIN    GPIO_PIN_1
#define PUMP_PWM_TIMER_CLOCK_HZ 84000000U
#define PUMP_PWM_PERIOD       4199U
/* 향후 확장 기록: 지금은 펌프 1개만 PA6 PWM으로 구동하지만,
 * 이후에는 데이터/상태 값에 따라 펌프 3개를 독립 PWM 채널로 제어할 예정입니다.
 * 그래서 펌프 판단 로직과 PWM 출력 로직을 Actuator 계층 안에 모아둡니다.
 */
#define ACTUATOR_CLASS_NONE   0xFFFFU
#define ACTUATOR_DEFAULT_DUTY_PERMILLE 100U
#define SIDE_AIR_DEFAULT_DUTY_PERMILLE 100U
#define SIDE_AIR_RUN_MAX_MS   7000U
#define ACTUATOR_CONFIDENCE_THRESHOLD  0.60f
#define ACTUATOR_STABLE_MOUTH_HOLD_MS  0U
#define ACTUATOR_RUN_MS      5000U
#define ACTUATOR_TEST_MS      800U
#define ORAL_AIR_VALVE_TEST_MS 800U

#define IMU_BRIDGE_TOKEN_MAX  16U
#define IMU_POSTURE_UNKNOWN   0U
#define IMU_POSTURE_NORMAL    1U
#define IMU_POSTURE_LEFT      2U
#define IMU_POSTURE_RIGHT     3U
#define IMU_POSTURE_SNIFFING  4U
#define IMU_POSTURE_ANGLE_OVER 5U
#define IMU_POSTURE_FRONT_LOW 6U

/* ICS-43434 I2S test path: HAL I2S 24/32-bit DMA stores each slot as two halfwords. */
#define I2S_DMA_SLOT_COUNT      2048U
#define I2S_DMA_HALFWORDS       (I2S_DMA_SLOT_COUNT * 2U)
#define I2S_BLOCK_HALFWORDS     (I2S_DMA_HALFWORDS / 2U)
#ifndef I2S_SELECTED_SLOT
#define I2S_SELECTED_SLOT       0U
#endif
#define I2S_PCM_BLOCK_SAMPLES   (I2S_BLOCK_HALFWORDS / 4U)

uint16_t adc_buffer[AUDIO_BUFFER_SIZE];
#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
uint16_t i2s_rx_dma[I2S_DMA_HALFWORDS];
uint16_t i2s_tx_dummy[I2S_DMA_HALFWORDS];
int16_t i2s_pcm_block[I2S_PCM_BLOCK_SAMPLES];
#endif

volatile uint8_t half_buffer_ready = 0;
volatile uint8_t full_buffer_ready = 0;
volatile uint8_t i2s_half_ready = 0;
volatile uint8_t i2s_full_ready = 0;

/* Debugger 확인용 변수 */
volatile uint32_t half_count = 0;
volatile uint32_t full_count = 0;
volatile uint32_t i2s_half_count = 0;
volatile uint32_t i2s_full_count = 0;
volatile uint32_t processed_half_count = 0;
volatile uint32_t processed_full_count = 0;
volatile uint32_t processed_i2s_half_count = 0;
volatile uint32_t processed_i2s_full_count = 0;

volatile uint16_t debug_adc_min = 4095;
volatile uint16_t debug_adc_max = 0;
volatile uint16_t debug_adc_mid = 0;
volatile uint16_t debug_adc_first = 0;
volatile uint16_t debug_adc_last = 0;

volatile int16_t debug_audio_min = 0;
volatile int16_t debug_audio_max = 0;
volatile int16_t debug_audio_mid = 0;

volatile uint32_t debug_peak_to_peak = 0;
volatile int32_t debug_i2s_raw_min = 0;
volatile int32_t debug_i2s_raw_max = 0;
volatile int32_t debug_i2s_raw_first = 0;
volatile int32_t debug_i2s_raw_last = 0;
volatile int16_t debug_i2s_pcm_min = 0;
volatile int16_t debug_i2s_pcm_max = 0;
volatile int16_t debug_i2s_pcm_mid = 0;
volatile uint32_t debug_i2s_pcm_p2p = 0;
volatile uint32_t debug_i2s_zero_count = 0;
volatile uint32_t debug_i2s_stuck_count = 0;
volatile uint32_t debug_i2s_clipping_count = 0;

/* USB Binary Streaming 확인용 변수 */
typedef struct {
    uint32_t magic;
    uint32_t seq;
    uint16_t samples;
    uint16_t reserved;
} AudioPacketHeader_t;

typedef struct {
    uint32_t magic;
    uint32_t seq;
    uint32_t audio_seq;
    uint16_t predicted;
    uint16_t status;
    uint32_t duration_ms;
    uint32_t input_blocks;
    float probabilities[BREATH_AI_LABEL_COUNT];
} AiPredictionPacket_t;

typedef struct {
    uint32_t magic;
    uint32_t seq;
    uint32_t tick_ms;
    uint32_t sample_count;
    int32_t red;
    int32_t ir;
    int32_t heart_rate_bpm;
    int32_t spo2_percent;
    float ratio;
    uint32_t flags;
    uint32_t i2c_error_count;
} Max30102TelemetryPacket_t;

typedef struct {
    uint32_t magic;
    uint32_t seq;
    uint32_t tick_ms;
    uint32_t rx_count;
    uint32_t valid_count;
    uint32_t invalid_count;
    uint32_t state;
    uint32_t last_state;
    uint32_t pending_state;
    uint32_t last_rx_byte;
    uint32_t side_pump_active;
    uint32_t side_valve_active;
    uint32_t oral_pump_active;
    uint32_t side_start_count;
    uint32_t side_stop_count;
    uint32_t side_safety_stop_count;
} ImuBridgeTelemetryPacket_t;

volatile uint32_t packet_seq = 0;
volatile uint32_t tx_busy_count = 0;
volatile uint32_t tx_timeout_count = 0;
volatile uint32_t tx_success_count = 0;
int16_t ai_pcm_frame[BREATH_AI_FRAME_SIZE];
#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
static float i2s_ai_pending_probabilities[BREATH_AI_LABEL_COUNT];
static breath_ai_status_t i2s_ai_pending_status = BREATH_AI_STATUS_OK;
static uint8_t i2s_ai_pending_ready = 0U;
#endif

volatile uint32_t ai_packet_seq = 0;
volatile uint32_t ai_input_block_count = 0;
volatile uint32_t ai_inference_count = 0;
volatile uint32_t ai_inference_error_count = 0;
volatile uint32_t ai_last_duration_ms = 0;
volatile uint16_t ai_raw_predicted = 0xFFFFU;
volatile float ai_raw_probability = 0.0f;
volatile uint16_t ai_last_predicted = 0;
volatile float ai_last_probability = 0.0f;
volatile uint16_t ai_stable_predicted = AI_NOISE_CLASS_INDEX;
volatile float ai_stable_probability = 0.0f;
volatile uint32_t ai_stable_vote_count = 0U;
volatile uint32_t ai_low_confidence_to_noise_count = 0U;

volatile uint16_t led_last_predicted = 0xFFFFU;
volatile uint32_t led_blink_count = 0;
volatile uint32_t led_mode = BREATH_LED_MODE_RAW;
static uint8_t class_led_active = 0U;
static uint8_t class_led_test_active = 0U;
static uint32_t class_led_on_tick = 0U;

volatile uint32_t pump_action_led_enabled = 1U;
volatile uint32_t pump_action_led_active = 0U;
volatile uint32_t pump_action_led_trigger_count = 0U;
volatile uint32_t pump_action_led_window_total = 0U;
volatile uint32_t pump_action_led_window_mouth = 0U;
volatile uint32_t pump_action_led_ai_paused_count = 0U;
static uint32_t pump_action_led_on_tick = 0U;
static uint32_t pump_action_led_ticks[PUMP_ACTION_LED_HISTORY_SIZE];
static uint8_t pump_action_led_mouth[PUMP_ACTION_LED_HISTORY_SIZE];
static uint32_t pump_action_led_history_count = 0U;
static uint32_t pump_action_led_history_next = 0U;

volatile uint32_t actuator_ai_control_enabled = 0U;
volatile uint32_t actuator_output_active = 0U;
volatile uint32_t actuator_duty_permille = ACTUATOR_DEFAULT_DUTY_PERMILLE;
volatile uint16_t actuator_last_trigger_class = ACTUATOR_CLASS_NONE;
volatile float actuator_last_trigger_probability = 0.0f;
volatile uint32_t actuator_mouth_window_count = 0U;
volatile uint32_t actuator_ai_paused_count = 0U;
volatile uint32_t actuator_start_count = 0U;
volatile uint32_t actuator_stop_count = 0U;
volatile uint32_t actuator_safety_stop_count = 0U;
volatile uint32_t actuator_stable_mouth_ms = 0U;
volatile uint32_t oral_air_valve_active = 0U;
volatile uint32_t oral_air_valve_on_count = 0U;
volatile uint32_t oral_air_valve_off_count = 0U;
volatile uint32_t side_air_pump_active = 0U;
volatile uint32_t side_air_duty_permille = SIDE_AIR_DEFAULT_DUTY_PERMILLE;
volatile uint32_t side_air_start_count = 0U;
volatile uint32_t side_air_stop_count = 0U;
volatile uint32_t side_air_safety_stop_count = 0U;
volatile uint32_t side_air_valve_active = 0U;
volatile uint32_t side_air_valve_on_count = 0U;
volatile uint32_t side_air_valve_off_count = 0U;
volatile uint32_t imu_bridge_state = IMU_POSTURE_UNKNOWN;
volatile uint32_t imu_bridge_last_state = IMU_POSTURE_UNKNOWN;
volatile uint32_t imu_bridge_rx_count = 0U;
volatile uint32_t imu_bridge_valid_count = 0U;
volatile uint32_t imu_bridge_invalid_count = 0U;
volatile uint32_t imu_bridge_last_rx_byte = 0U;
volatile uint32_t imu_bridge_telemetry_enabled = 0U;
volatile uint32_t imu_bridge_telemetry_packet_count = 0U;

static uint16_t ai_stable_history_labels[AI_STABLE_HISTORY_SIZE];
static float ai_stable_history_confidences[AI_STABLE_HISTORY_SIZE];
static uint8_t ai_stable_history_count = 0U;
static uint8_t ai_stable_history_next = 0U;
static uint8_t actuator_stable_mouth_active = 0U;
static uint32_t actuator_stable_mouth_start_tick = 0U;
static uint8_t actuator_manual_pulse_active = 0U;
static uint32_t actuator_on_tick = 0U;
static uint32_t actuator_manual_off_tick = 0U;
static uint8_t oral_air_valve_manual_active = 0U;
static uint8_t oral_air_valve_manual_pulse_active = 0U;
static uint32_t oral_air_valve_manual_off_tick = 0U;
static uint32_t side_air_on_tick = 0U;
static uint8_t imu_uart_rx_byte = 0U;
static char imu_bridge_token[IMU_BRIDGE_TOKEN_MAX];
static uint8_t imu_bridge_token_len = 0U;
static volatile uint8_t imu_bridge_pending_valid = 0U;
static volatile uint32_t imu_bridge_pending_state = IMU_POSTURE_UNKNOWN;
static uint32_t imu_bridge_telemetry_last_tick = 0U;
static uint32_t imu_bridge_telemetry_seq = 0U;

volatile uint32_t max30102_telemetry_enabled = 0U;
volatile uint32_t max30102_telemetry_packet_count = 0U;
static uint32_t max30102_telemetry_last_tick = 0U;

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
/* 함수 설명: 보드 클럭 트리와 PLL 설정을 초기화합니다. */
void SystemClock_Config(void);
/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_GPIO_Init(void);
/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_DMA_Init(void);
/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_ADC1_Init(void);
/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_TIM2_Init(void);
/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_TIM3_Init(void);
/* 함수 설명: MAX30102 산소포화도 센서용 I2C1을 초기화합니다. */
static void MX_I2C1_Init(void);
/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_I2S2_Init(void);
/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_USART1_UART_Init(void);
/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_USART2_UART_Init(void);
/* 함수 설명: MAX30102 RED/IR/SpO2 값을 USB CDC telemetry packet으로 주기 전송합니다. */
static void Max30102Telemetry_Service(void);
static void SideAirbag_Init(void);
static void SideAirbag_Service(void);
static void ImuBridge_Init(void);
static void ImuBridge_Service(void);
static void ImuBridgeTelemetry_Service(void);
static void ImuBridgeHandleByte(uint8_t byte);
static void ImuBridgeParseToken(const char *token);

/* USER CODE BEGIN 0 */

/* 함수 설명: ADC 블록의 최소/최대/평균 값을 계산해 마이크 입력 상태 디버깅에 사용합니다. */
#if (MIC_BACKEND == MIC_BACKEND_ADC_MAX9814)
static void AnalyzeAudioBlock(uint16_t *buf, uint32_t len)
{
    uint16_t min_val = 4095;
    uint16_t max_val = 0;

    for (uint32_t i = 0; i < len; i++)
    {
        uint16_t v = buf[i];

        if (v < min_val) min_val = v;
        if (v > max_val) max_val = v;
    }

    debug_adc_min = min_val;
    debug_adc_max = max_val;
    debug_adc_mid = buf[len / 2];
    debug_adc_first = buf[0];
    debug_adc_last = buf[len - 1];

    debug_audio_min = (int16_t)((int32_t)min_val - ADC_DC_OFFSET);
    debug_audio_max = (int16_t)((int32_t)max_val - ADC_DC_OFFSET);
    debug_audio_mid = (int16_t)((int32_t)debug_adc_mid - ADC_DC_OFFSET);

    debug_peak_to_peak = (uint32_t)(max_val - min_val);
}

/* 함수 설명: USB CDC 전송 완료를 제한 시간 동안 기다리며 패킷을 전송합니다. */
#endif
static uint8_t CDC_Transmit_WithTimeout(uint8_t *data, uint16_t len)
{
    uint32_t start_tick = HAL_GetTick();

    while (CDC_Transmit_FS(data, len) == USBD_BUSY)
    {
        tx_busy_count++;

        if ((HAL_GetTick() - start_tick) > 10)
        {
            tx_timeout_count++;
            return 0;
        }
    }

    tx_success_count++;
    return 1;
}

/* 함수 설명: ADC 샘플 블록을 PC 실시간 모니터가 읽는 오디오 패킷 형식으로 전송합니다. */
static void SendAudioPacketWithFormat(uint16_t *data, uint16_t sample_count, uint16_t audio_format)
{
    AudioPacketHeader_t header;

    header.magic = AUDIO_MAGIC;
    header.seq = packet_seq;
    header.samples = sample_count;
    header.reserved = audio_format;

    if (!CDC_Transmit_WithTimeout((uint8_t*)&header, sizeof(header)))
    {
        return;
    }

    if (!CDC_Transmit_WithTimeout((uint8_t*)data, sample_count * sizeof(uint16_t)))
    {
        return;
    }

    packet_seq++;
}

static void ADC_ONLY_UNUSED SendAudioPacket(uint16_t *data, uint16_t sample_count)
{
    SendAudioPacketWithFormat(data, sample_count, AUDIO_FORMAT_ADC_U16);
}

void Max30102Telemetry_SetEnabled(uint32_t enabled)
{
    max30102_telemetry_enabled = (enabled != 0U) ? 1U : 0U;
    max30102_telemetry_last_tick = HAL_GetTick();
    if (max30102_telemetry_enabled != 0U) {
        max30102_telemetry_packet_count = 0U;
    }
}

uint32_t Max30102Telemetry_IsEnabled(void)
{
    return max30102_telemetry_enabled;
}

static uint32_t Max30102TelemetryFlags(const Max30102Spo2State *state)
{
    uint32_t flags = 0U;

    if (state == NULL) {
        return 0U;
    }

    if (state->initialized != 0U) flags |= (1UL << 0);
    if (state->present != 0U) flags |= (1UL << 1);
    if (state->finger_detected != 0U) flags |= (1UL << 2);
    if (state->spo2_ok != 0U) flags |= (1UL << 3);
    flags |= (((uint32_t)state->status) & 0xFFU) << 8;

    return flags;
}

static void Max30102Telemetry_Service(void)
{
    Max30102Spo2State state;
    Max30102TelemetryPacket_t packet;
    const uint32_t now = HAL_GetTick();

    if (max30102_telemetry_enabled == 0U) {
        return;
    }

    if ((now - max30102_telemetry_last_tick) < MAX30102_TELEMETRY_PERIOD_MS) {
        return;
    }

    max30102_telemetry_last_tick = now;
    Max30102Spo2_GetState(&state);

    packet.magic = MAX30102_MAGIC;
    packet.seq = max30102_telemetry_packet_count;
    packet.tick_ms = now;
    packet.sample_count = state.sample_count;
    packet.red = state.red;
    packet.ir = state.ir;
    packet.heart_rate_bpm = state.heart_rate_bpm;
    packet.spo2_percent = state.spo2_percent;
    packet.ratio = state.ratio;
    packet.flags = Max30102TelemetryFlags(&state);
    packet.i2c_error_count = state.i2c_error_count;

    if (CDC_Transmit_WithTimeout((uint8_t*)&packet, sizeof(packet)) != 0U) {
        max30102_telemetry_packet_count++;
    }
}

/* 함수 설명: 32비트 계산값을 int16 범위로 제한합니다. */
static int16_t ClampToI16(int32_t value)
{
    if (value > 32767) {
        return 32767;
    }

    if (value < -32768) {
        return -32768;
    }

    return (int16_t)value;
}

/* ICS-43434는 24-bit signed sample을 32-bit slot의 상위 비트에 싣습니다.
 * STM32 HAL I2S DMA는 24/32-bit slot 하나를 uint16_t 2개로 저장하므로
 * MSW/LSW를 조립한 뒤 24-bit 값을 int16 PCM으로 줄입니다.
 */
#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
static int16_t I2S_RawToPcm16(uint16_t msw, uint16_t lsw, int32_t *raw24_out)
{
    const uint32_t word32 = ((uint32_t)msw << 16) | (uint32_t)lsw;
    const int32_t raw24 = ((int32_t)word32) >> 8;
    const int32_t pcm32 = (raw24 >> 8) * I2S_TO_PCM_GAIN;

    if (raw24_out != NULL) {
        *raw24_out = raw24;
    }

    return ClampToI16(pcm32);
}

static uint32_t ConvertI2SBlockToPcm16(uint16_t *raw, uint32_t halfword_count, int16_t *pcm, uint32_t pcm_capacity)
{
    uint32_t out = 0U;
    uint32_t zero_count = 0U;
    uint32_t clipping_count = 0U;
    int32_t raw_min = 0;
    int32_t raw_max = 0;
    int32_t raw_first = 0;
    int32_t raw_last = 0;
    int16_t pcm_min = 0;
    int16_t pcm_max = 0;

    if ((raw == NULL) || (pcm == NULL) || (pcm_capacity == 0U)) {
        return 0U;
    }

    for (uint32_t i = 0U; (i + 3U) < halfword_count && out < pcm_capacity; i += 4U)
    {
        const uint32_t slot_base = i + (I2S_SELECTED_SLOT * 2U);
        int32_t raw24 = 0;
        const int16_t pcm16 = I2S_RawToPcm16(raw[slot_base], raw[slot_base + 1U], &raw24);

        if (out == 0U) {
            raw_min = raw24;
            raw_max = raw24;
            raw_first = raw24;
            pcm_min = pcm16;
            pcm_max = pcm16;
        } else {
            if (raw24 < raw_min) raw_min = raw24;
            if (raw24 > raw_max) raw_max = raw24;
            if (pcm16 < pcm_min) pcm_min = pcm16;
            if (pcm16 > pcm_max) pcm_max = pcm16;
        }

        if (raw24 == 0) {
            zero_count++;
        }
        if ((pcm16 == 32767) || (pcm16 == -32768)) {
            clipping_count++;
        }

        raw_last = raw24;
        pcm[out] = pcm16;
        out++;
    }

    if (out > 0U) {
        debug_i2s_raw_min = raw_min;
        debug_i2s_raw_max = raw_max;
        debug_i2s_raw_first = raw_first;
        debug_i2s_raw_last = raw_last;
        debug_i2s_pcm_min = pcm_min;
        debug_i2s_pcm_max = pcm_max;
        debug_i2s_pcm_mid = pcm[out / 2U];
        debug_i2s_pcm_p2p = (uint32_t)((int32_t)pcm_max - (int32_t)pcm_min);
        debug_i2s_zero_count = zero_count;
        debug_i2s_clipping_count = clipping_count;
        if (raw_min == raw_max) {
            debug_i2s_stuck_count++;
        }
    }

    return out;
}

static void ProcessAndSendPcm16(int16_t *buf, uint32_t len)
{
    uint32_t offset = 0U;

    while (offset < len)
    {
        const uint32_t remaining = len - offset;
        const uint16_t send_count = (remaining >= PACKET_SAMPLES) ? PACKET_SAMPLES : (uint16_t)remaining;

        SendAudioPacketWithFormat((uint16_t*)&buf[offset], send_count, AUDIO_FORMAT_PCM16);
        offset += send_count;
    }
}

/* 함수 설명: 5개 분류 결과를 PE0~PE3/PE7 LED 핀 중 하나로 매핑합니다. */
#endif
static uint16_t ClassLedPinFromPrediction(uint16_t predicted)
{
    switch (predicted) {
        case 0U:
            return LED_MOUTH_EXHALE_PIN;
        case 1U:
            return LED_MOUTH_INHALE_PIN;
        case 2U:
            return LED_NASAL_EXHALE_PIN;
        case 3U:
            return LED_NASAL_INHALE_PIN;
        case 4U:
            return LED_NOISE_PIN;
        default:
            return 0U;
    }
}

/* 함수 설명: 모든 클래스 LED를 끄고 점멸 상태를 초기화합니다. */
static void ClassLedAllOff(void)
{
    HAL_GPIO_WritePin(CLASS_LED_PORT, CLASS_LED_ALL_PINS, GPIO_PIN_RESET);
    class_led_active = 0U;
}

/* 함수 설명: 예측된 클래스에 해당하는 LED만 짧게 켜서 추론 결과를 표시합니다. */
/* LED mode selector: stable is for normal operation, raw is for model debugging. */
static uint16_t ADC_ONLY_UNUSED ClassLedPredictionForMode(uint16_t raw_predicted, uint16_t stable_predicted)
{
    if (led_mode == BREATH_LED_MODE_OFF) {
        return ACTUATOR_CLASS_NONE;
    }

    if (led_mode == BREATH_LED_MODE_RAW) {
        return raw_predicted;
    }

    return stable_predicted;
}

void BreathLed_SetMode(uint32_t mode)
{
    class_led_test_active = 0U;
    if (mode == BREATH_LED_MODE_RAW) {
        led_mode = BREATH_LED_MODE_RAW;
    } else if (mode == BREATH_LED_MODE_OFF) {
        led_mode = BREATH_LED_MODE_OFF;
    } else {
        led_mode = BREATH_LED_MODE_STABLE;
    }
    ClassLedAllOff();
}

uint32_t BreathLed_GetMode(void)
{
    return led_mode;
}

void BreathLed_TestOff(void)
{
    class_led_test_active = 0U;
    led_mode = BREATH_LED_MODE_OFF;
    ClassLedAllOff();
    HAL_GPIO_WritePin(PUMP_ACTION_LED_PORT, PUMP_ACTION_LED_PIN, GPIO_PIN_RESET);
}

void BreathLed_TestClass(uint32_t class_index)
{
    const uint16_t pin = ClassLedPinFromPrediction((uint16_t)class_index);

    led_mode = BREATH_LED_MODE_OFF;
    class_led_test_active = 1U;
    HAL_GPIO_WritePin(CLASS_LED_PORT, CLASS_LED_ALL_PINS, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(PUMP_ACTION_LED_PORT, PUMP_ACTION_LED_PIN, GPIO_PIN_RESET);
    class_led_active = 0U;

    if (pin != 0U) {
        HAL_GPIO_WritePin(CLASS_LED_PORT, pin, GPIO_PIN_SET);
        led_last_predicted = (uint16_t)class_index;
    }
}

void BreathLed_TestPumpIndicator(void)
{
    led_mode = BREATH_LED_MODE_OFF;
    class_led_test_active = 1U;
    ClassLedAllOff();
    HAL_GPIO_WritePin(PUMP_ACTION_LED_PORT, PUMP_ACTION_LED_PIN, GPIO_PIN_SET);
}

void BreathLed_TestAll(void)
{
    led_mode = BREATH_LED_MODE_OFF;
    class_led_test_active = 1U;
    class_led_active = 0U;
    HAL_GPIO_WritePin(CLASS_LED_PORT, CLASS_LED_ALL_PINS, GPIO_PIN_SET);
    HAL_GPIO_WritePin(PUMP_ACTION_LED_PORT, PUMP_ACTION_LED_PIN, GPIO_PIN_SET);
}

static void ADC_ONLY_UNUSED ClassLedPulsePrediction(uint16_t predicted)
{
    const uint16_t pin = ClassLedPinFromPrediction(predicted);

    if (class_led_test_active != 0U) {
        return;
    }

    HAL_GPIO_WritePin(CLASS_LED_PORT, CLASS_LED_ALL_PINS, GPIO_PIN_RESET);
    if (pin == 0U) {
        class_led_active = 0U;
        return;
    }

    HAL_GPIO_WritePin(CLASS_LED_PORT, pin, GPIO_PIN_SET);
    class_led_on_tick = HAL_GetTick();
    class_led_active = 1U;
    led_last_predicted = predicted;
    led_blink_count++;
}

/* 함수 설명: 점멸 시간이 지난 LED를 메인 루프에서 non-blocking 방식으로 끕니다. */
static void ClassLedService(void)
{
    if (class_led_test_active != 0U) {
        return;
    }

    if (class_led_active == 0U) {
        return;
    }

    if ((HAL_GetTick() - class_led_on_tick) >= CLASS_LED_PULSE_MS) {
        ClassLedAllOff();
    }
}

/* 함수 설명: AI 후처리 히스토리를 지우고 stable 상태를 noise로 되돌립니다. */
static void ADC_ONLY_UNUSED AiStableReset(void)
{
    for (uint32_t i = 0U; i < AI_STABLE_HISTORY_SIZE; ++i) {
        ai_stable_history_labels[i] = AI_NOISE_CLASS_INDEX;
        ai_stable_history_confidences[i] = 0.0f;
    }
    ai_stable_history_count = 0U;
    ai_stable_history_next = 0U;
    ai_stable_predicted = AI_NOISE_CLASS_INDEX;
    ai_stable_probability = 0.0f;
    ai_stable_vote_count = 0U;
}

static uint8_t AiPredictionIsValid(uint16_t predicted)
{
    return (predicted < BREATH_AI_LABEL_COUNT) ? 1U : 0U;
}

static uint8_t AiPredictionIsNoise(uint16_t predicted)
{
    return (predicted == AI_NOISE_CLASS_INDEX) ? 1U : 0U;
}

/* 함수 설명: 낮은 confidence의 호흡 후보를 noise로 낮추고 최근 6회 다수결로 stable prediction을 만듭니다. */
static uint16_t ADC_ONLY_UNUSED AiStableUpdate(
    uint16_t raw_predicted,
    const float probabilities[BREATH_AI_LABEL_COUNT],
    float *stable_confidence,
    uint32_t *stable_votes)
{
    uint16_t candidate = AI_NOISE_CLASS_INDEX;
    float candidate_confidence = 0.0f;
    uint32_t counts[BREATH_AI_LABEL_COUNT] = {0U};
    float sums[BREATH_AI_LABEL_COUNT] = {0.0f};
    uint16_t stable = AI_NOISE_CLASS_INDEX;
    uint32_t best_count = 0U;
    float best_mean = 0.0f;

    if ((probabilities != NULL) && (AiPredictionIsValid(raw_predicted) != 0U)) {
        candidate = raw_predicted;
        candidate_confidence = probabilities[raw_predicted];

        if ((AiPredictionIsNoise(candidate) == 0U) &&
            (candidate_confidence < AI_CONFIDENCE_GATE)) {
            candidate = AI_NOISE_CLASS_INDEX;
            candidate_confidence = probabilities[AI_NOISE_CLASS_INDEX];
            ai_low_confidence_to_noise_count++;
        }
    }

    ai_stable_history_labels[ai_stable_history_next] = candidate;
    ai_stable_history_confidences[ai_stable_history_next] = candidate_confidence;
    ai_stable_history_next++;
    if (ai_stable_history_next >= AI_STABLE_HISTORY_SIZE) {
        ai_stable_history_next = 0U;
    }
    if (ai_stable_history_count < AI_STABLE_HISTORY_SIZE) {
        ai_stable_history_count++;
    }

    for (uint32_t i = 0U; i < ai_stable_history_count; ++i) {
        const uint16_t label = ai_stable_history_labels[i];
        if (AiPredictionIsValid(label) != 0U) {
            counts[label]++;
            sums[label] += ai_stable_history_confidences[i];
        }
    }

    best_count = counts[AI_NOISE_CLASS_INDEX];
    if (best_count > 0U) {
        best_mean = sums[AI_NOISE_CLASS_INDEX] / (float)best_count;
    } else if (probabilities != NULL) {
        best_mean = probabilities[AI_NOISE_CLASS_INDEX];
    }

    for (uint32_t label = 0U; label < AI_NOISE_CLASS_INDEX; ++label) {
        if (counts[label] >= AI_STABLE_MIN_VOTES) {
            const float mean = sums[label] / (float)counts[label];
            if ((mean >= AI_STABLE_AVG_CONFIDENCE_GATE) &&
                ((stable == AI_NOISE_CLASS_INDEX) ||
                 (counts[label] > best_count) ||
                 ((counts[label] == best_count) && (mean > best_mean)))) {
                stable = (uint16_t)label;
                best_count = counts[label];
                best_mean = mean;
            }
        }
    }

    ai_stable_predicted = stable;
    ai_stable_probability = best_mean;
    ai_stable_vote_count = best_count;

    if (stable_confidence != NULL) {
        *stable_confidence = best_mean;
    }
    if (stable_votes != NULL) {
        *stable_votes = best_count;
    }

    return stable;
}

/* 함수 설명: ADC 샘플을 AI 입력 프레임 크기에 맞춰 DC 제거 후 int16 PCM으로 변환합니다. */
static void ActuatorResetMouthHistory(void);
static void ActuatorOutputStart(uint16_t trigger_class, float probability);

static uint8_t ActuatorIsMouthClass(uint16_t predicted)
{
    return ((predicted == 0U) || (predicted == 1U)) ? 1U : 0U;
}

static void PumpActionLedResetWindow(void)
{
    for (uint32_t i = 0U; i < PUMP_ACTION_LED_HISTORY_SIZE; ++i) {
        pump_action_led_ticks[i] = 0U;
        pump_action_led_mouth[i] = 0U;
    }
    pump_action_led_history_count = 0U;
    pump_action_led_history_next = 0U;
    pump_action_led_window_total = 0U;
    pump_action_led_window_mouth = 0U;
}

static void PumpActionLedOff(void)
{
    HAL_GPIO_WritePin(PUMP_ACTION_LED_PORT, PUMP_ACTION_LED_PIN, GPIO_PIN_RESET);
    pump_action_led_active = 0U;
}

static uint8_t PumpActionLedIsBlocking(void)
{
    return ((pump_action_led_enabled != 0U) && (pump_action_led_active != 0U)) ? 1U : 0U;
}

static uint8_t ImuBridgeAllowsOralPump(void)
{
    return ((imu_bridge_state != IMU_POSTURE_SNIFFING) &&
            (imu_bridge_state != IMU_POSTURE_ANGLE_OVER)) ? 1U : 0U;
}

static void PumpActionLedStart(uint16_t trigger_class)
{
    if (ImuBridgeAllowsOralPump() == 0U) {
        PumpActionLedOff();
        PumpActionLedResetWindow();
        return;
    }

    pump_action_led_on_tick = HAL_GetTick();
    pump_action_led_active = 1U;
    pump_action_led_trigger_count++;
    HAL_GPIO_WritePin(PUMP_ACTION_LED_PORT, PUMP_ACTION_LED_PIN, GPIO_PIN_SET);
    ActuatorOutputStart(trigger_class, 1.0f);
    ClassLedAllOff();
    PumpActionLedResetWindow();
}

static void PumpActionLedService(void)
{
    if (pump_action_led_enabled == 0U) {
        PumpActionLedOff();
        PumpActionLedResetWindow();
        return;
    }

    if (pump_action_led_active == 0U) {
        return;
    }

    if ((HAL_GetTick() - pump_action_led_on_tick) >= PUMP_ACTION_LED_ACTIVE_MS) {
        PumpActionLedOff();
        PumpActionLedResetWindow();
        AiStableReset();
        ActuatorResetMouthHistory();
        BreathAI_ResetFeatureStream();
    }
}

static void PumpActionLedRecordPrediction(uint16_t led_predicted)
{
    const uint32_t now = HAL_GetTick();
    uint32_t total = 0U;
    uint32_t mouth = 0U;
    const uint8_t is_mouth = (ActuatorIsMouthClass(led_predicted) != 0U) ? 1U : 0U;

    if ((pump_action_led_enabled == 0U) || (pump_action_led_active != 0U)) {
        return;
    }

    pump_action_led_ticks[pump_action_led_history_next] = now;
    pump_action_led_mouth[pump_action_led_history_next] = is_mouth;
    pump_action_led_history_next =
        (pump_action_led_history_next + 1U) % PUMP_ACTION_LED_HISTORY_SIZE;
    if (pump_action_led_history_count < PUMP_ACTION_LED_HISTORY_SIZE) {
        pump_action_led_history_count++;
    }

    for (uint32_t i = 0U; i < pump_action_led_history_count; ++i) {
        const uint32_t age = now - pump_action_led_ticks[i];
        if (age <= PUMP_ACTION_LED_WINDOW_MS) {
            total++;
            if (pump_action_led_mouth[i] != 0U) {
                mouth++;
            }
        }
    }

    pump_action_led_window_total = total;
    pump_action_led_window_mouth = mouth;

    if ((total >= PUMP_ACTION_LED_MIN_SAMPLES) &&
        ((mouth * 100U) >= (total * PUMP_ACTION_LED_MOUTH_PERCENT))) {
        PumpActionLedStart(led_predicted);
    }
}

void BreathPumpLed_SetEnabled(uint32_t enabled)
{
    pump_action_led_enabled = (enabled != 0U) ? 1U : 0U;
    PumpActionLedResetWindow();
    if (pump_action_led_enabled == 0U) {
        PumpActionLedOff();
    }
}

uint32_t BreathPumpLed_IsEnabled(void)
{
    return pump_action_led_enabled;
}

uint32_t BreathPumpLed_IsActive(void)
{
    return pump_action_led_active;
}

static uint32_t ActuatorClampDuty(uint32_t duty_permille)
{
    if (duty_permille > 1000U) {
        return 1000U;
    }

    return duty_permille;
}

static void ActuatorApplyDuty(uint32_t duty_permille)
{
    const uint32_t duty = ActuatorClampDuty(duty_permille);
    const uint32_t compare = ((PUMP_PWM_PERIOD + 1U) * duty) / 1000U;

    __HAL_TIM_SET_COMPARE(&htim3, PUMP_PWM_CHANNEL, compare);
}

static void OralAirValveSet(uint8_t enabled)
{
    const uint32_t next_active = (enabled != 0U) ? 1U : 0U;

    if (oral_air_valve_active != next_active) {
        if (next_active != 0U) {
            oral_air_valve_on_count++;
        } else {
            oral_air_valve_off_count++;
        }
    }

    oral_air_valve_active = next_active;
    HAL_GPIO_WritePin(
        ORAL_AIR_VALVE_PORT,
        ORAL_AIR_VALVE_PIN,
        (next_active != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static void ActuatorResetMouthHistory(void)
{
    actuator_stable_mouth_active = 0U;
    actuator_stable_mouth_start_tick = 0U;
    actuator_mouth_window_count = 0U;
    actuator_stable_mouth_ms = 0U;
}

static void ActuatorOutputStop(uint8_t safety_stop)
{
    if (actuator_output_active != 0U) {
        actuator_stop_count++;
    }

    ActuatorApplyDuty(0U);
    actuator_output_active = 0U;
    actuator_manual_pulse_active = 0U;

    if (safety_stop != 0U) {
        actuator_safety_stop_count++;
    }
}

static void ActuatorOutputStart(uint16_t trigger_class, float probability)
{
    const uint32_t now = HAL_GetTick();

    if (actuator_output_active == 0U) {
        actuator_start_count++;
    }

    actuator_on_tick = now;
    actuator_output_active = 1U;
    actuator_last_trigger_class = trigger_class;
    actuator_last_trigger_probability = probability;
    ActuatorApplyDuty(actuator_duty_permille);
    ActuatorResetMouthHistory();
}

static void OralAirValve_Service(void)
{
    const uint32_t now = HAL_GetTick();

    if (oral_air_valve_manual_pulse_active != 0U) {
        if ((now - oral_air_valve_manual_off_tick) < 0x80000000U) {
            oral_air_valve_manual_pulse_active = 0U;
            oral_air_valve_manual_active = 0U;
            OralAirValveSet(0U);
        }
    }
}

void OralAirValve_ManualOn(void)
{
    actuator_ai_control_enabled = 0U;
    ActuatorResetMouthHistory();
    ActuatorOutputStop(0U);
    oral_air_valve_manual_active = 1U;
    oral_air_valve_manual_pulse_active = 0U;
    OralAirValveSet(1U);
}

void OralAirValve_ManualOff(void)
{
    oral_air_valve_manual_active = 0U;
    oral_air_valve_manual_pulse_active = 0U;
    OralAirValveSet(0U);
}

void OralAirValve_ManualPulse(uint32_t duration_ms)
{
    const uint32_t pulse_ms = (duration_ms == 0U) ? ORAL_AIR_VALVE_TEST_MS : duration_ms;

    actuator_ai_control_enabled = 0U;
    ActuatorResetMouthHistory();
    ActuatorOutputStop(0U);
    oral_air_valve_manual_active = 1U;
    oral_air_valve_manual_pulse_active = 1U;
    oral_air_valve_manual_off_tick = HAL_GetTick() + pulse_ms;
    OralAirValveSet(1U);
}

uint32_t OralAirValve_IsActive(void)
{
    return oral_air_valve_active;
}

static void ADC_ONLY_UNUSED ActuatorHandlePrediction(uint16_t predicted, float probability)
{
    const uint32_t now = HAL_GetTick();
    uint32_t held_ms;

    if (actuator_ai_control_enabled == 0U) {
        ActuatorResetMouthHistory();
        return;
    }

    if (ImuBridgeAllowsOralPump() == 0U) {
        ActuatorResetMouthHistory();
        return;
    }

    if (actuator_output_active != 0U) {
        return;
    }

    if ((ActuatorIsMouthClass(predicted) == 0U) ||
        (probability < ACTUATOR_CONFIDENCE_THRESHOLD)) {
        ActuatorResetMouthHistory();
        return;
    }

    if (actuator_stable_mouth_active == 0U) {
        actuator_stable_mouth_active = 1U;
        actuator_stable_mouth_start_tick = now;
        actuator_stable_mouth_ms = 0U;
        if (ACTUATOR_STABLE_MOUTH_HOLD_MS == 0U) {
            ActuatorOutputStart(predicted, probability);
        }
        return;
    }

    held_ms = now - actuator_stable_mouth_start_tick;
    actuator_stable_mouth_ms = held_ms;
    actuator_mouth_window_count = held_ms;

    if (held_ms >= ACTUATOR_STABLE_MOUTH_HOLD_MS) {
        ActuatorOutputStart(predicted, probability);
    }
}

static void BreathActuator_Init(void)
{
    ActuatorApplyDuty(0U);
    (void)HAL_TIM_PWM_Start(&htim3, PUMP_PWM_CHANNEL);
    ActuatorApplyDuty(0U);
    OralAirValveSet(0U);
}

static void BreathActuator_Service(void)
{
    const uint32_t now = HAL_GetTick();

    OralAirValve_Service();

    if (actuator_manual_pulse_active != 0U) {
        if ((now - actuator_manual_off_tick) < 0x80000000U) {
            ActuatorOutputStop(0U);
            return;
        }
    }

    if (actuator_output_active == 0U) {
        return;
    }

    if ((now - actuator_on_tick) >= ACTUATOR_RUN_MS) {
        ActuatorOutputStop(1U);
    }
}

void BreathActuator_SetAiControlEnabled(uint32_t enabled)
{
    actuator_ai_control_enabled = (enabled != 0U) ? 1U : 0U;
    ActuatorResetMouthHistory();

    if (actuator_ai_control_enabled == 0U) {
        ActuatorOutputStop(0U);
    }
}

uint32_t BreathActuator_IsAiControlEnabled(void)
{
    return actuator_ai_control_enabled;
}

void BreathActuator_SetDutyPermille(uint32_t duty_permille)
{
    actuator_duty_permille = ActuatorClampDuty(duty_permille);
}

uint32_t BreathActuator_GetDutyPermille(void)
{
    return actuator_duty_permille;
}

void BreathActuator_ManualOn(uint32_t duty_permille)
{
    BreathActuator_SetAiControlEnabled(0U);
    BreathActuator_SetDutyPermille(duty_permille);
    actuator_manual_pulse_active = 0U;
    ActuatorOutputStart(ACTUATOR_CLASS_NONE, 0.0f);
}

void BreathActuator_ManualPulse(uint32_t duty_permille, uint32_t duration_ms)
{
    const uint32_t pulse_ms = (duration_ms == 0U) ? ACTUATOR_TEST_MS : duration_ms;

    BreathActuator_SetAiControlEnabled(0U);
    BreathActuator_SetDutyPermille(duty_permille);
    actuator_manual_pulse_active = 1U;
    actuator_manual_off_tick = HAL_GetTick() + pulse_ms;
    ActuatorOutputStart(ACTUATOR_CLASS_NONE, 0.0f);
}

void BreathActuator_Off(void)
{
    BreathActuator_SetAiControlEnabled(0U);
    ActuatorResetMouthHistory();
    ActuatorOutputStop(0U);
    OralAirValve_ManualOff();
}

static void SideAirbagApplyDuty(uint32_t duty_permille)
{
    const uint32_t duty = ActuatorClampDuty(duty_permille);
    const uint32_t compare = ((PUMP_PWM_PERIOD + 1U) * duty) / 1000U;

    __HAL_TIM_SET_COMPARE(&htim3, SIDE_PUMP_PWM_CHANNEL, compare);
}

static void SideAirbagValveSet(uint8_t enabled)
{
    const uint32_t next_active = (enabled != 0U) ? 1U : 0U;

    if (side_air_valve_active != next_active) {
        if (next_active != 0U) {
            side_air_valve_on_count++;
        } else {
            side_air_valve_off_count++;
        }
    }

    side_air_valve_active = next_active;
    HAL_GPIO_WritePin(
        SIDE_AIR_VALVE_PORT,
        SIDE_AIR_VALVE_PIN,
        (next_active != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static void SideAirbagStopPump(uint8_t safety_stop)
{
    if (side_air_pump_active != 0U) {
        side_air_stop_count++;
    }

    SideAirbagApplyDuty(0U);
    side_air_pump_active = 0U;

    if (safety_stop != 0U) {
        side_air_safety_stop_count++;
    }
}

static void SideAirbagStartPump(void)
{
    if (side_air_pump_active == 0U) {
        side_air_start_count++;
    }

    SideAirbagValveSet(0U);
    side_air_on_tick = HAL_GetTick();
    side_air_pump_active = 1U;
    SideAirbagApplyDuty(side_air_duty_permille);
}

static void SideAirbag_Init(void)
{
    SideAirbagApplyDuty(0U);
    (void)HAL_TIM_PWM_Start(&htim3, SIDE_PUMP_PWM_CHANNEL);
    SideAirbagApplyDuty(0U);
    SideAirbagValveSet(0U);
}

static void SideAirbag_Service(void)
{
    const uint32_t now = HAL_GetTick();

    if (side_air_pump_active == 0U) {
        return;
    }

    if ((now - side_air_on_tick) >= SIDE_AIR_RUN_MAX_MS) {
        SideAirbagStopPump(1U);
    }
}

static char ImuBridgeToUpper(char ch)
{
    if ((ch >= 'a') && (ch <= 'z')) {
        return (char)(ch - ('a' - 'A'));
    }

    return ch;
}

static uint8_t ImuBridgeTokenEquals(const char *token, const char *expected)
{
    return (strcmp(token, expected) == 0) ? 1U : 0U;
}

static void ImuBridgeSetPendingState(uint32_t state)
{
    imu_bridge_pending_state = state;
    imu_bridge_pending_valid = 1U;
    imu_bridge_valid_count++;
}

static void ImuBridgeParseToken(const char *token)
{
    uint32_t state = IMU_POSTURE_UNKNOWN;

    if ((token == NULL) || (token[0] == '\0')) {
        return;
    }

    if ((ImuBridgeTokenEquals(token, "L") != 0U) ||
        (ImuBridgeTokenEquals(token, "LEFT") != 0U)) {
        state = IMU_POSTURE_LEFT;
    } else if ((ImuBridgeTokenEquals(token, "R") != 0U) ||
               (ImuBridgeTokenEquals(token, "RIGHT") != 0U)) {
        state = IMU_POSTURE_RIGHT;
    } else if ((ImuBridgeTokenEquals(token, "N") != 0U) ||
               (ImuBridgeTokenEquals(token, "NORMAL") != 0U)) {
        state = IMU_POSTURE_NORMAL;
    } else if ((ImuBridgeTokenEquals(token, "S") != 0U) ||
               (ImuBridgeTokenEquals(token, "SNIFFING") != 0U)) {
        state = IMU_POSTURE_SNIFFING;
    } else if ((ImuBridgeTokenEquals(token, "F") != 0U) ||
               (ImuBridgeTokenEquals(token, "FRONT") != 0U) ||
               (ImuBridgeTokenEquals(token, "FLAT") != 0U) ||
               (ImuBridgeTokenEquals(token, "FRONT_LOW") != 0U)) {
        state = IMU_POSTURE_FRONT_LOW;
    } else if ((ImuBridgeTokenEquals(token, "A") != 0U) ||
               (ImuBridgeTokenEquals(token, "O") != 0U) ||
               (ImuBridgeTokenEquals(token, "ANGLE_OVER") != 0U) ||
               (ImuBridgeTokenEquals(token, "OVER") != 0U)) {
        state = IMU_POSTURE_ANGLE_OVER;
    } else {
        imu_bridge_invalid_count++;
        return;
    }

    ImuBridgeSetPendingState(state);
}

static void ImuBridgeFlushToken(void)
{
    if (imu_bridge_token_len == 0U) {
        return;
    }

    imu_bridge_token[imu_bridge_token_len] = '\0';
    ImuBridgeParseToken(imu_bridge_token);
    imu_bridge_token_len = 0U;
}

static void ImuBridgeHandleByte(uint8_t byte)
{
    const char ch = ImuBridgeToUpper((char)byte);

    imu_bridge_rx_count++;
    imu_bridge_last_rx_byte = (uint32_t)byte;

    if ((ch == '\r') || (ch == '\n') || (ch == ',') || (ch == ';') || (ch == ' ')) {
        ImuBridgeFlushToken();
        return;
    }

    if (imu_bridge_token_len < (IMU_BRIDGE_TOKEN_MAX - 1U)) {
        imu_bridge_token[imu_bridge_token_len] = ch;
        imu_bridge_token_len++;
    } else {
        imu_bridge_token_len = 0U;
        imu_bridge_invalid_count++;
        return;
    }

    if ((imu_bridge_token_len == 1U) &&
        ((ch == 'L') || (ch == 'R') || (ch == 'N') || (ch == 'S') || (ch == 'F') || (ch == 'A'))) {
        ImuBridgeFlushToken();
    }
}

static void ImuBridge_Init(void)
{
    imu_bridge_state = IMU_POSTURE_UNKNOWN;
    imu_bridge_last_state = IMU_POSTURE_UNKNOWN;
    imu_bridge_pending_valid = 0U;
    imu_bridge_token_len = 0U;
    (void)HAL_UART_Receive_IT(&huart1, &imu_uart_rx_byte, 1U);
}

static void ImuBridge_Service(void)
{
    uint32_t state;

    if (imu_bridge_pending_valid == 0U) {
        return;
    }

    state = imu_bridge_pending_state;
    imu_bridge_pending_valid = 0U;
    imu_bridge_last_state = imu_bridge_state;
    imu_bridge_state = state;

    if ((state == IMU_POSTURE_LEFT) || (state == IMU_POSTURE_RIGHT)) {
        SideAirbagStartPump();
        return;
    }

    if ((state == IMU_POSTURE_NORMAL) || (state == IMU_POSTURE_FRONT_LOW)) {
        SideAirbagStopPump(0U);
        SideAirbagValveSet(1U);
        return;
    }

    if (state == IMU_POSTURE_SNIFFING) {
        ActuatorOutputStop(0U);
        PumpActionLedOff();
        PumpActionLedResetWindow();
        AiStableReset();
        BreathAI_ResetFeatureStream();
        return;
    }

    if (state == IMU_POSTURE_ANGLE_OVER) {
        ActuatorOutputStop(1U);
        PumpActionLedOff();
        PumpActionLedResetWindow();
        AiStableReset();
        BreathAI_ResetFeatureStream();
        SideAirbagStopPump(1U);
        SideAirbagValveSet(1U);
    }
}

void ImuBridgeTelemetry_SetEnabled(uint32_t enabled)
{
    imu_bridge_telemetry_enabled = (enabled != 0U) ? 1U : 0U;
    imu_bridge_telemetry_last_tick = 0U;
}

uint32_t ImuBridgeTelemetry_IsEnabled(void)
{
    return imu_bridge_telemetry_enabled;
}

void ImuBridgeTelemetry_ResetCounters(void)
{
    imu_bridge_rx_count = 0U;
    imu_bridge_valid_count = 0U;
    imu_bridge_invalid_count = 0U;
    imu_bridge_last_rx_byte = 0U;
    imu_bridge_telemetry_packet_count = 0U;
    imu_bridge_telemetry_seq = 0U;
}

static void ImuBridgeTelemetry_Service(void)
{
    ImuBridgeTelemetryPacket_t packet;
    const uint32_t now = HAL_GetTick();

    if (imu_bridge_telemetry_enabled == 0U) {
        return;
    }

    if ((now - imu_bridge_telemetry_last_tick) < IMU_BRIDGE_TELEMETRY_PERIOD_MS) {
        return;
    }

    imu_bridge_telemetry_last_tick = now;
    memset(&packet, 0, sizeof(packet));

    packet.magic = IMU_BRIDGE_MAGIC;
    packet.seq = imu_bridge_telemetry_seq++;
    packet.tick_ms = now;
    packet.rx_count = imu_bridge_rx_count;
    packet.valid_count = imu_bridge_valid_count;
    packet.invalid_count = imu_bridge_invalid_count;
    packet.state = imu_bridge_state;
    packet.last_state = imu_bridge_last_state;
    packet.pending_state = (imu_bridge_pending_valid != 0U) ? imu_bridge_pending_state : IMU_POSTURE_UNKNOWN;
    packet.last_rx_byte = imu_bridge_last_rx_byte;
    packet.side_pump_active = side_air_pump_active;
    packet.side_valve_active = side_air_valve_active;
    packet.oral_pump_active = actuator_output_active;
    packet.side_start_count = side_air_start_count;
    packet.side_stop_count = side_air_stop_count;
    packet.side_safety_stop_count = side_air_safety_stop_count;

    if (CDC_Transmit_WithTimeout((uint8_t*)&packet, sizeof(packet)) != 0U) {
        imu_bridge_telemetry_packet_count++;
    }
}

#if (MIC_BACKEND == MIC_BACKEND_ADC_MAX9814)
static uint8_t PrepareAiPcmFrameFromAdc(uint16_t *buf, uint32_t len)
{
    if (BreathAI_IsLiveInferenceEnabled() == 0U) {
        AiStableReset();
        ActuatorResetMouthHistory();
        return 0U;
    }

    if (actuator_output_active != 0U) {
        actuator_ai_paused_count++;
        AiStableReset();
        return 0U;
    }

    if (PumpActionLedIsBlocking() != 0U) {
        pump_action_led_ai_paused_count++;
        AiStableReset();
        ActuatorResetMouthHistory();
        return 0U;
    }

    if ((buf == NULL) || (len < BREATH_AI_FRAME_SIZE)) {
        return 0U;
    }

    ai_input_block_count++;
    if ((ai_input_block_count % AI_INFERENCE_BLOCK_STRIDE) != 0U) {
        return 0U;
    }

    const uint32_t start = len - BREATH_AI_FRAME_SIZE;
    for (uint32_t i = 0; i < BREATH_AI_FRAME_SIZE; ++i) {
        const int32_t centered = (int32_t)buf[start + i] - ADC_DC_OFFSET;
        ai_pcm_frame[i] = ClampToI16(centered * ADC_TO_PCM_GAIN);
    }

    return 1U;
}

/* 함수 설명: STM AI 예측 결과와 확률을 PC 모니터용 바이너리 패킷으로 전송합니다. */
#endif

#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
static uint8_t PrepareAiPcmFrameFromPcm16(const int16_t *buf, uint32_t len)
{
    if (BreathAI_IsLiveInferenceEnabled() == 0U) {
        BreathAI_ResetFeatureStream();
        i2s_ai_pending_ready = 0U;
        AiStableReset();
        ActuatorResetMouthHistory();
        return 0U;
    }

    if (actuator_output_active != 0U) {
        actuator_ai_paused_count++;
        BreathAI_ResetFeatureStream();
        i2s_ai_pending_ready = 0U;
        AiStableReset();
        return 0U;
    }

    if (PumpActionLedIsBlocking() != 0U) {
        pump_action_led_ai_paused_count++;
        BreathAI_ResetFeatureStream();
        i2s_ai_pending_ready = 0U;
        AiStableReset();
        ActuatorResetMouthHistory();
        return 0U;
    }

    if ((buf == NULL) || (len == 0U)) {
        return 0U;
    }

    {
        const uint32_t start_tick = HAL_GetTick();
        uint8_t prediction_ready = 0U;
        const breath_ai_status_t status = BreathAI_ProcessPcmI16Stream(
            buf,
            len,
            i2s_ai_pending_probabilities,
            &prediction_ready);

        if ((status != BREATH_AI_STATUS_OK) || (prediction_ready != 0U)) {
            i2s_ai_pending_status = status;
            i2s_ai_pending_ready = prediction_ready;
            ai_last_duration_ms = HAL_GetTick() - start_tick;
            ai_input_block_count++;
            return 1U;
        }
    }

    return 0U;
}
#endif

static void SendAiPredictionPacket(
    breath_ai_status_t status,
    const float probabilities[BREATH_AI_LABEL_COUNT],
    uint32_t audio_seq_snapshot)
{
    AiPredictionPacket_t packet;
    uint16_t raw_predicted = 0xFFFFU;
    uint16_t stable_predicted = AI_NOISE_CLASS_INDEX;
    uint16_t led_predicted = AI_NOISE_CLASS_INDEX;
    float stable_probability = 0.0f;
    uint32_t stable_votes = 0U;

    memset(&packet, 0, sizeof(packet));

    if ((status == BREATH_AI_STATUS_OK) && (probabilities != NULL)) {
        raw_predicted = (uint16_t)BreathAI_ArgmaxProbabilities(probabilities);
        memcpy(packet.probabilities, probabilities, sizeof(packet.probabilities));
        ai_raw_predicted = raw_predicted;
        ai_raw_probability = probabilities[raw_predicted];
        stable_predicted = AiStableUpdate(
            raw_predicted,
            probabilities,
            &stable_probability,
            &stable_votes);
        ai_last_predicted = stable_predicted;
        ai_last_probability = stable_probability;
        if (PumpActionLedIsBlocking() == 0U) {
            led_predicted = ClassLedPredictionForMode(raw_predicted, stable_predicted);
            ClassLedPulsePrediction(led_predicted);
            PumpActionLedRecordPrediction(led_predicted);
            if (PumpActionLedIsBlocking() == 0U) {
                ActuatorHandlePrediction(stable_predicted, stable_probability);
            } else {
                ActuatorResetMouthHistory();
            }
        } else {
            ClassLedAllOff();
            ActuatorResetMouthHistory();
        }
    } else {
        AiStableReset();
        ClassLedAllOff();
        ActuatorResetMouthHistory();
    }

    packet.magic = AI_MAGIC;
    packet.seq = ai_packet_seq;
    packet.audio_seq = audio_seq_snapshot;
    packet.predicted = stable_predicted;
    packet.status = (uint16_t)status;
    packet.duration_ms = ai_last_duration_ms;
    packet.input_blocks = ai_input_block_count;

    (void)CDC_Transmit_WithTimeout((uint8_t*)&packet, sizeof(packet));
    ai_packet_seq++;
}

/* 함수 설명: 준비된 PCM 프레임으로 AI 추론을 실행하고 결과 패킷을 보냅니다. */
static void RunAiInferenceAndSend(uint32_t audio_seq_snapshot)
{
#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
    ai_inference_count++;

    if (i2s_ai_pending_status != BREATH_AI_STATUS_OK) {
        ai_inference_error_count++;
    }

    SendAiPredictionPacket(
        i2s_ai_pending_status,
        (i2s_ai_pending_ready != 0U) ? i2s_ai_pending_probabilities : NULL,
        audio_seq_snapshot);
    i2s_ai_pending_ready = 0U;
#else
    float probabilities[BREATH_AI_LABEL_COUNT];
    breath_ai_status_t status;
    const uint32_t start_tick = HAL_GetTick();

    status = BreathAI_PredictPcmI16(ai_pcm_frame, probabilities);
    ai_last_duration_ms = HAL_GetTick() - start_tick;
    ai_inference_count++;

    if (status != BREATH_AI_STATUS_OK) {
        ai_inference_error_count++;
    }

    SendAiPredictionPacket(status, probabilities, audio_seq_snapshot);
#endif
}

/* 함수 설명: DMA half/full 버퍼를 오디오 패킷으로 나누고 필요하면 AI 프레임도 갱신합니다. */
#if (MIC_BACKEND == MIC_BACKEND_ADC_MAX9814)
static void ProcessAndSend(uint16_t *buf, uint32_t len)
{
    uint32_t offset = 0;

    while (offset < len)
    {
        uint32_t remaining = len - offset;
        uint16_t send_count;

        if (remaining >= PACKET_SAMPLES)
        {
            send_count = PACKET_SAMPLES;
        }
        else
        {
            send_count = (uint16_t)remaining;
        }

        SendAudioPacket(&buf[offset], send_count);
        offset += send_count;
    }
}
#endif

/* USER CODE END 0 */

/* 함수 설명: HAL, USB, ADC DMA, AI 초기화를 끝낸 뒤 수집/전송 루프를 계속 실행합니다. */
int main(void)
{
  HAL_Init();

  SystemClock_Config();

  MX_GPIO_Init();
  MX_DMA_Init();
  MX_ADC1_Init();
  MX_TIM2_Init();
  MX_TIM3_Init();
  MX_I2C1_Init();
  MX_I2S2_Init();
  MX_USART1_UART_Init();
  MX_USART2_UART_Init();
  MX_USB_DEVICE_Init();

  /* USER CODE BEGIN 2 */

  BreathAI_RunBootSelfTest();
  BreathActuator_Init();
  SideAirbag_Init();
  ImuBridge_Init();
  (void)Max30102Spo2_Init(&hi2c1, SPO2_STATUS_LED_PORT, SPO2_STATUS_LED_PIN);

#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
  BreathAI_SetLiveInferenceEnabled(1U);
  BreathActuator_Off();
  if (HAL_I2SEx_TransmitReceive_DMA(&hi2s2, i2s_tx_dummy, i2s_rx_dma, I2S_DMA_SLOT_COUNT) != HAL_OK)
  {
      Error_Handler();
  }
#else
  HAL_ADC_Start_DMA(&hadc1, (uint32_t*)adc_buffer, AUDIO_BUFFER_SIZE);
  HAL_TIM_Base_Start(&htim2);
#endif

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
      ClassLedService();
      PumpActionLedService();
      BreathActuator_Service();
      SideAirbag_Service();
      ImuBridge_Service();
      ImuBridgeTelemetry_Service();
      Max30102Spo2_Service();
      Max30102Telemetry_Service();

#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
      if (i2s_half_ready)
      {
          uint8_t run_ai;
          uint32_t audio_seq_snapshot;
          uint32_t pcm_count;

          i2s_half_ready = 0U;
          processed_i2s_half_count++;

          pcm_count = ConvertI2SBlockToPcm16(&i2s_rx_dma[0], I2S_BLOCK_HALFWORDS, i2s_pcm_block, I2S_PCM_BLOCK_SAMPLES);
          run_ai = PrepareAiPcmFrameFromPcm16(i2s_pcm_block, pcm_count);
          audio_seq_snapshot = packet_seq;
          ProcessAndSendPcm16(i2s_pcm_block, pcm_count);
          if (run_ai != 0U) {
              RunAiInferenceAndSend(audio_seq_snapshot);
          }
      }

      if (i2s_full_ready)
      {
          uint8_t run_ai;
          uint32_t audio_seq_snapshot;
          uint32_t pcm_count;

          i2s_full_ready = 0U;
          processed_i2s_full_count++;

          pcm_count = ConvertI2SBlockToPcm16(&i2s_rx_dma[I2S_BLOCK_HALFWORDS], I2S_BLOCK_HALFWORDS, i2s_pcm_block, I2S_PCM_BLOCK_SAMPLES);
          run_ai = PrepareAiPcmFrameFromPcm16(i2s_pcm_block, pcm_count);
          audio_seq_snapshot = packet_seq;
          ProcessAndSendPcm16(i2s_pcm_block, pcm_count);
          if (run_ai != 0U) {
              RunAiInferenceAndSend(audio_seq_snapshot);
          }
      }
#else
      if (half_buffer_ready)
      {
          uint8_t run_ai;
          uint32_t audio_seq_snapshot;

          half_buffer_ready = 0;
          processed_half_count++;

          run_ai = PrepareAiPcmFrameFromAdc(&adc_buffer[0], AUDIO_HALF_SIZE);
          audio_seq_snapshot = packet_seq;
          AnalyzeAudioBlock(&adc_buffer[0], AUDIO_HALF_SIZE);
          ProcessAndSend(&adc_buffer[0], AUDIO_HALF_SIZE);
          if (run_ai != 0U) {
              RunAiInferenceAndSend(audio_seq_snapshot);
          }
      }

      if (full_buffer_ready)
      {
          uint8_t run_ai;
          uint32_t audio_seq_snapshot;

          full_buffer_ready = 0;
          processed_full_count++;

          run_ai = PrepareAiPcmFrameFromAdc(&adc_buffer[AUDIO_HALF_SIZE], AUDIO_HALF_SIZE);
          audio_seq_snapshot = packet_seq;
          AnalyzeAudioBlock(&adc_buffer[AUDIO_HALF_SIZE], AUDIO_HALF_SIZE);
          ProcessAndSend(&adc_buffer[AUDIO_HALF_SIZE], AUDIO_HALF_SIZE);
          if (run_ai != 0U) {
              RunAiInferenceAndSend(audio_seq_snapshot);
          }
      }
#endif

    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/* 함수 설명: 보드 클럭 트리와 PLL 설정을 초기화합니다. */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 4;
  RCC_OscInitStruct.PLL.PLLN = 168;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;

  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                              | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_ADC1_Init(void)
{
  ADC_ChannelConfTypeDef sConfig = {0};

  hadc1.Instance = ADC1;
  hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;
  hadc1.Init.Resolution = ADC_RESOLUTION_12B;
  hadc1.Init.ScanConvMode = DISABLE;
  hadc1.Init.ContinuousConvMode = DISABLE;
  hadc1.Init.DiscontinuousConvMode = DISABLE;
  hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_RISING;
  hadc1.Init.ExternalTrigConv = ADC_EXTERNALTRIGCONV_T2_TRGO;
  hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc1.Init.NbrOfConversion = 1;
  hadc1.Init.DMAContinuousRequests = ENABLE;
  hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;

  if (HAL_ADC_Init(&hadc1) != HAL_OK)
  {
    Error_Handler();
  }

  sConfig.Channel = ADC_CHANNEL_1;
  sConfig.Rank = 1;
  sConfig.SamplingTime = ADC_SAMPLETIME_144CYCLES;

  if (HAL_ADC_ConfigChannel(&hadc1, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
}

/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_I2S2_Init(void)
{
  hi2s2.Instance = SPI2;
#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
  hi2s2.Init.Mode = I2S_MODE_MASTER_TX;
#else
  hi2s2.Init.Mode = I2S_MODE_MASTER_RX;
#endif
  hi2s2.Init.Standard = I2S_STANDARD_PHILIPS;
#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
  hi2s2.Init.DataFormat = I2S_DATAFORMAT_24B;
#else
  hi2s2.Init.DataFormat = I2S_DATAFORMAT_16B;
#endif
  hi2s2.Init.MCLKOutput = I2S_MCLKOUTPUT_DISABLE;
  hi2s2.Init.AudioFreq = I2S_AUDIOFREQ_16K;
  hi2s2.Init.CPOL = I2S_CPOL_LOW;
  hi2s2.Init.ClockSource = I2S_CLOCK_PLL;
#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
  hi2s2.Init.FullDuplexMode = I2S_FULLDUPLEXMODE_ENABLE;
#else
  hi2s2.Init.FullDuplexMode = I2S_FULLDUPLEXMODE_DISABLE;
#endif

  if (HAL_I2S_Init(&hi2s2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_TIM2_Init(void)
{
  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 0;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 5249;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

  if (HAL_TIM_Base_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }

  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;

  if (HAL_TIM_ConfigClockSource(&htim2, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }

  sMasterConfig.MasterOutputTrigger = TIM_TRGO_UPDATE;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;

  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
}

/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_TIM3_Init(void)
{
  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  __HAL_RCC_TIM3_CLK_ENABLE();

  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 0;
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = PUMP_PWM_PERIOD;
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

  if (HAL_TIM_Base_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }

  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;

  if (HAL_TIM_ConfigClockSource(&htim3, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }

  if (HAL_TIM_PWM_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }

  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;

  if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }

  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;

  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, PUMP_PWM_CHANNEL) != HAL_OK)
  {
    Error_Handler();
  }

  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, SIDE_PUMP_PWM_CHANNEL) != HAL_OK)
  {
    Error_Handler();
  }
}

/* 함수 설명: MAX30102 산소포화도 센서용 I2C1을 표준 모드 100 kHz로 초기화합니다. */
static void MX_I2C1_Init(void)
{
  hi2c1.Instance = I2C1;
  hi2c1.Init.ClockSpeed = 100000;
  hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;

  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }
}

/* 함수 설명: ESP32-S3 IMU BLE bridge에서 들어오는 자세 상태 문자를 USART1 9600bps로 수신합니다. */
static void MX_USART1_UART_Init(void)
{
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 9600;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;

  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
}

/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_USART2_UART_Init(void)
{
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 460800;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;

  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_DMA_Init(void)
{
  __HAL_RCC_DMA2_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();

  HAL_NVIC_SetPriority(DMA1_Stream3_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream3_IRQn);

#if (MIC_BACKEND == MIC_BACKEND_I2S_ICS43434)
  HAL_NVIC_SetPriority(DMA1_Stream4_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream4_IRQn);
#endif

  HAL_NVIC_SetPriority(DMA1_Stream6_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream6_IRQn);

  HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
}

/* 함수 설명: CubeMX가 생성한 주변장치 초기화 함수를 실행합니다. */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOE_CLK_ENABLE();

  HAL_GPIO_WritePin(CLASS_LED_PORT, CLASS_LED_ALL_PINS, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(PUMP_ACTION_LED_PORT, PUMP_ACTION_LED_PIN, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(SPO2_STATUS_LED_PORT, SPO2_STATUS_LED_PIN, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ORAL_AIR_VALVE_PORT, ORAL_AIR_VALVE_PIN, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(SIDE_AIR_VALVE_PORT, SIDE_AIR_VALVE_PIN, GPIO_PIN_RESET);

  GPIO_InitStruct.Pin = CLASS_LED_ALL_PINS | PUMP_ACTION_LED_PIN | SPO2_STATUS_LED_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(CLASS_LED_PORT, &GPIO_InitStruct);

  GPIO_InitStruct.Pin = PUMP_PWM_PIN | SIDE_PUMP_PWM_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF2_TIM3;
  HAL_GPIO_Init(PUMP_PWM_PORT, &GPIO_InitStruct);

  GPIO_InitStruct.Pin = ORAL_AIR_VALVE_PIN | SIDE_AIR_VALVE_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(ORAL_AIR_VALVE_PORT, &GPIO_InitStruct);
}

/* USER CODE BEGIN 4 */

/* 함수 설명: ADC DMA 앞쪽 절반 수집 완료를 메인 루프에 알립니다. */
void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef* hadc)
{
    if (hadc->Instance == ADC1)
    {
        half_count++;
        half_buffer_ready = 1;
    }
}

/* 함수 설명: ADC DMA 뒤쪽 절반 수집 완료를 메인 루프에 알립니다. */
void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef* hadc)
{
    if (hadc->Instance == ADC1)
    {
        full_count++;
        full_buffer_ready = 1;
    }
}

void HAL_I2S_RxHalfCpltCallback(I2S_HandleTypeDef *hi2s)
{
    if (hi2s->Instance == SPI2)
    {
        i2s_half_count++;
        i2s_half_ready = 1U;
    }
}

void HAL_I2S_RxCpltCallback(I2S_HandleTypeDef *hi2s)
{
    if (hi2s->Instance == SPI2)
    {
        i2s_full_count++;
        i2s_full_ready = 1U;
    }
}

void HAL_I2SEx_TxRxHalfCpltCallback(I2S_HandleTypeDef *hi2s)
{
    if (hi2s->Instance == SPI2)
    {
        i2s_half_count++;
        i2s_half_ready = 1U;
    }
}

void HAL_I2SEx_TxRxCpltCallback(I2S_HandleTypeDef *hi2s)
{
    if (hi2s->Instance == SPI2)
    {
        i2s_full_count++;
        i2s_full_ready = 1U;
    }
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1)
    {
        ImuBridgeHandleByte(imu_uart_rx_byte);
        (void)HAL_UART_Receive_IT(&huart1, &imu_uart_rx_byte, 1U);
    }
}

/* USER CODE END 4 */

/* 함수 설명: Error_Handler 함수의 입력을 검사하고 해당 모듈의 핵심 처리를 수행합니다. */
void Error_Handler(void)
{
  __disable_irq();

  while (1)
  {
  }
}

#ifdef USE_FULL_ASSERT
/* 함수 설명: assert_failed 함수의 입력을 검사하고 해당 모듈의 핵심 처리를 수행합니다. */
void assert_failed(uint8_t *file, uint32_t line)
{
}
#endif
