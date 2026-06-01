#include "max30102_spo2.h"

#include <string.h>

#define MAX30102_I2C_ADDR_7BIT          0x57U
#define MAX30102_I2C_ADDR               (MAX30102_I2C_ADDR_7BIT << 1)

#define MAX30102_REG_INTR_STATUS_1      0x00U
#define MAX30102_REG_INTR_STATUS_2      0x01U
#define MAX30102_REG_INTR_ENABLE_1      0x02U
#define MAX30102_REG_INTR_ENABLE_2      0x03U
#define MAX30102_REG_FIFO_WR_PTR        0x04U
#define MAX30102_REG_OVF_COUNTER        0x05U
#define MAX30102_REG_FIFO_RD_PTR        0x06U
#define MAX30102_REG_FIFO_DATA          0x07U
#define MAX30102_REG_FIFO_CONFIG        0x08U
#define MAX30102_REG_MODE_CONFIG        0x09U
#define MAX30102_REG_SPO2_CONFIG        0x0AU
#define MAX30102_REG_LED1_PA            0x0CU
#define MAX30102_REG_LED2_PA            0x0DU
#define MAX30102_REG_PART_ID            0xFFU

#define MAX30102_MODE_RESET             0x40U
#define MAX30102_MODE_SPO2              0x03U
#define MAX30102_FIFO_ROLLOVER_EN       0x10U
#define MAX30102_FIFO_ALMOST_FULL       0x0FU
#define MAX30102_SPO2_ADC_16384         0x60U
#define MAX30102_SPO2_SR_100HZ          0x04U
#define MAX30102_SPO2_PW_411US          0x03U

#define MAX30102_POLL_MS                10U
#define MAX30102_I2C_TIMEOUT_MS         3U
#define MAX30102_MAX_SAMPLES_PER_POLL   4U
#define MAX30102_WIN                    60U
#define MAX30102_RATE_SIZE              8U
#define MAX30102_FINGER_IR_THRESHOLD    30000L
#define MAX30102_HR_HP_ALPHA            0.95f
#define MAX30102_HR_THRESHOLD           200.0f
#define MAX30102_SPO2_MIN_IR_AC         50.0f
#define MAX30102_ABNORMAL_BLINK_MS      100U

typedef struct {
    I2C_HandleTypeDef *hi2c;
    GPIO_TypeDef *led_port;
    uint16_t led_pin;
    Max30102Spo2State state;
    int32_t ir_win[MAX30102_WIN];
    int32_t red_win[MAX30102_WIN];
    uint8_t win_index;
    uint8_t win_count;
    uint8_t rates[MAX30102_RATE_SIZE];
    uint8_t rate_spot;
    uint8_t rate_count;
    uint32_t last_beat_tick;
    float hp_out;
    float prev_ir;
    uint8_t was_negative;
    float spo2_smooth;
    uint32_t last_poll_tick;
    uint32_t last_blink_tick;
    uint8_t blink_state;
} Max30102Context;

static Max30102Context g_max30102;

static HAL_StatusTypeDef Max30102_ReadReg(uint8_t reg, uint8_t *value)
{
    return HAL_I2C_Mem_Read(g_max30102.hi2c, MAX30102_I2C_ADDR, reg,
                            I2C_MEMADD_SIZE_8BIT, value, 1U,
                            MAX30102_I2C_TIMEOUT_MS);
}

static HAL_StatusTypeDef Max30102_WriteReg(uint8_t reg, uint8_t value)
{
    return HAL_I2C_Mem_Write(g_max30102.hi2c, MAX30102_I2C_ADDR, reg,
                             I2C_MEMADD_SIZE_8BIT, &value, 1U,
                             MAX30102_I2C_TIMEOUT_MS);
}

static HAL_StatusTypeDef Max30102_ReadBytes(uint8_t reg, uint8_t *data, uint16_t len)
{
    return HAL_I2C_Mem_Read(g_max30102.hi2c, MAX30102_I2C_ADDR, reg,
                            I2C_MEMADD_SIZE_8BIT, data, len,
                            MAX30102_I2C_TIMEOUT_MS);
}

static void Max30102_ResetRuntime(void)
{
    memset(g_max30102.ir_win, 0, sizeof(g_max30102.ir_win));
    memset(g_max30102.red_win, 0, sizeof(g_max30102.red_win));
    memset(g_max30102.rates, 0, sizeof(g_max30102.rates));
    g_max30102.win_index = 0U;
    g_max30102.win_count = 0U;
    g_max30102.rate_spot = 0U;
    g_max30102.rate_count = 0U;
    g_max30102.last_beat_tick = 0U;
    g_max30102.hp_out = 0.0f;
    g_max30102.prev_ir = 0.0f;
    g_max30102.was_negative = 1U;
    g_max30102.spo2_smooth = 0.0f;
    g_max30102.state.finger_detected = 0U;
    g_max30102.state.spo2_ok = 0U;
    g_max30102.state.heart_rate_bpm = 0;
    g_max30102.state.spo2_percent = 0;
    g_max30102.state.ratio = 0.0f;
    g_max30102.state.status = MAX30102_SPO2_STATUS_OFF;
}

static void Max30102_SetLed(GPIO_PinState state)
{
    if (g_max30102.led_port != NULL) {
        HAL_GPIO_WritePin(g_max30102.led_port, g_max30102.led_pin, state);
    }
}

static void Max30102_UpdateStatusLed(void)
{
    const uint32_t now = HAL_GetTick();

    if ((g_max30102.state.present == 0U) ||
        (g_max30102.state.finger_detected == 0U) ||
        (g_max30102.state.spo2_ok == 0U)) {
        g_max30102.state.status = MAX30102_SPO2_STATUS_OFF;
        g_max30102.blink_state = 0U;
        Max30102_SetLed(GPIO_PIN_RESET);
        return;
    }

    if (g_max30102.state.spo2_percent >= 95) {
        g_max30102.state.status = MAX30102_SPO2_STATUS_NORMAL;
        g_max30102.blink_state = 1U;
        Max30102_SetLed(GPIO_PIN_SET);
        return;
    }

    g_max30102.state.status = MAX30102_SPO2_STATUS_ABNORMAL;
    if ((now - g_max30102.last_blink_tick) >= MAX30102_ABNORMAL_BLINK_MS) {
        g_max30102.last_blink_tick = now;
        g_max30102.blink_state = (g_max30102.blink_state == 0U) ? 1U : 0U;
        Max30102_SetLed(g_max30102.blink_state ? GPIO_PIN_SET : GPIO_PIN_RESET);
    }
}

static void Max30102_ProcessHeartRate(int32_t ir)
{
    const uint32_t now = HAL_GetTick();
    g_max30102.hp_out = MAX30102_HR_HP_ALPHA *
        (g_max30102.hp_out + (float)ir - g_max30102.prev_ir);
    g_max30102.prev_ir = (float)ir;

    if ((g_max30102.hp_out > MAX30102_HR_THRESHOLD) &&
        (g_max30102.was_negative != 0U)) {
        const uint32_t delta = now - g_max30102.last_beat_tick;
        g_max30102.was_negative = 0U;
        g_max30102.last_beat_tick = now;

        if (delta > 0U) {
            const float bpm = 60000.0f / (float)delta;
            if ((bpm >= 40.0f) && (bpm <= 200.0f)) {
                int32_t sum = 0;
                g_max30102.rates[g_max30102.rate_spot++] = (uint8_t)bpm;
                g_max30102.rate_spot %= MAX30102_RATE_SIZE;
                if (g_max30102.rate_count < MAX30102_RATE_SIZE) {
                    g_max30102.rate_count++;
                }
                for (uint8_t i = 0U; i < g_max30102.rate_count; ++i) {
                    sum += g_max30102.rates[i];
                }
                g_max30102.state.heart_rate_bpm =
                    (g_max30102.rate_count > 0U) ? (sum / g_max30102.rate_count) : 0;
            }
        }
    } else if (g_max30102.hp_out < 0.0f) {
        g_max30102.was_negative = 1U;
    }
}

static void Max30102_ProcessSpo2Window(void)
{
    int32_t ir_min;
    int32_t ir_max;
    int32_t red_min;
    int32_t red_max;
    int32_t ir_dc;
    int32_t red_dc;
    float ir_ac;
    float red_ac;
    float ratio;
    int32_t spo2;

    if (g_max30102.win_count < 20U) {
        return;
    }

    ir_min = g_max30102.ir_win[0];
    ir_max = g_max30102.ir_win[0];
    red_min = g_max30102.red_win[0];
    red_max = g_max30102.red_win[0];

    for (uint8_t i = 1U; i < g_max30102.win_count; ++i) {
        if (g_max30102.ir_win[i] < ir_min) ir_min = g_max30102.ir_win[i];
        if (g_max30102.ir_win[i] > ir_max) ir_max = g_max30102.ir_win[i];
        if (g_max30102.red_win[i] < red_min) red_min = g_max30102.red_win[i];
        if (g_max30102.red_win[i] > red_max) red_max = g_max30102.red_win[i];
    }

    ir_dc = (ir_max + ir_min) / 2;
    red_dc = (red_max + red_min) / 2;
    ir_ac = (float)(ir_max - ir_min);
    red_ac = (float)(red_max - red_min);

    if ((ir_dc <= 0) || (red_dc <= 0) || (ir_ac <= MAX30102_SPO2_MIN_IR_AC)) {
        return;
    }

    ratio = (red_ac / (float)red_dc) / (ir_ac / (float)ir_dc);
    spo2 = (int32_t)((-45.06f * ratio * ratio) + (30.354f * ratio) + 94.845f);
    if (spo2 < 80) spo2 = 80;
    if (spo2 > 100) spo2 = 100;

    g_max30102.spo2_smooth =
        (g_max30102.spo2_smooth == 0.0f) ? (float)spo2 :
        ((0.9f * g_max30102.spo2_smooth) + (0.1f * (float)spo2));
    g_max30102.state.spo2_percent = (int32_t)g_max30102.spo2_smooth;
    g_max30102.state.ratio = ratio;
    g_max30102.state.spo2_ok = 1U;
}

static void Max30102_ProcessSample(int32_t red, int32_t ir)
{
    g_max30102.state.red = red;
    g_max30102.state.ir = ir;
    g_max30102.state.sample_count++;

    if (ir < MAX30102_FINGER_IR_THRESHOLD) {
        Max30102_ResetRuntime();
        g_max30102.state.red = red;
        g_max30102.state.ir = ir;
        return;
    }

    g_max30102.state.finger_detected = 1U;
    Max30102_ProcessHeartRate(ir);

    g_max30102.ir_win[g_max30102.win_index] = ir;
    g_max30102.red_win[g_max30102.win_index] = red;
    g_max30102.win_index = (uint8_t)((g_max30102.win_index + 1U) % MAX30102_WIN);
    if (g_max30102.win_count < MAX30102_WIN) {
        g_max30102.win_count++;
    }

    Max30102_ProcessSpo2Window();
}

static void Max30102_PollFifo(void)
{
    uint8_t wr_ptr;
    uint8_t rd_ptr;
    uint8_t available;
    uint8_t samples_to_read;

    if ((Max30102_ReadReg(MAX30102_REG_FIFO_WR_PTR, &wr_ptr) != HAL_OK) ||
        (Max30102_ReadReg(MAX30102_REG_FIFO_RD_PTR, &rd_ptr) != HAL_OK)) {
        g_max30102.state.i2c_error_count++;
        return;
    }

    wr_ptr &= 0x1FU;
    rd_ptr &= 0x1FU;
    available = (wr_ptr >= rd_ptr) ? (uint8_t)(wr_ptr - rd_ptr) :
        (uint8_t)(32U + wr_ptr - rd_ptr);
    samples_to_read = available;
    if (samples_to_read > MAX30102_MAX_SAMPLES_PER_POLL) {
        samples_to_read = MAX30102_MAX_SAMPLES_PER_POLL;
    }

    for (uint8_t i = 0U; i < samples_to_read; ++i) {
        uint8_t raw[6];
        int32_t red;
        int32_t ir;
        if (Max30102_ReadBytes(MAX30102_REG_FIFO_DATA, raw, sizeof(raw)) != HAL_OK) {
            g_max30102.state.i2c_error_count++;
            return;
        }

        red = (((int32_t)raw[0] << 16) | ((int32_t)raw[1] << 8) | raw[2]) & 0x3FFFF;
        ir = (((int32_t)raw[3] << 16) | ((int32_t)raw[4] << 8) | raw[5]) & 0x3FFFF;
        Max30102_ProcessSample(red, ir);
    }
}

uint8_t Max30102Spo2_Init(I2C_HandleTypeDef *hi2c, GPIO_TypeDef *led_port, uint16_t led_pin)
{
    uint8_t part_id = 0U;
    uint8_t dummy = 0U;
    g_max30102.hi2c = hi2c;
    g_max30102.led_port = led_port;
    g_max30102.led_pin = led_pin;
    memset(&g_max30102.state, 0, sizeof(g_max30102.state));
    Max30102_ResetRuntime();
    Max30102_SetLed(GPIO_PIN_RESET);

    if (hi2c == NULL) {
        return 0U;
    }

    if (Max30102_ReadReg(MAX30102_REG_PART_ID, &part_id) != HAL_OK) {
        g_max30102.state.i2c_error_count++;
        return 0U;
    }

    g_max30102.state.part_id = part_id;
    g_max30102.state.present = 1U;

    (void)Max30102_WriteReg(MAX30102_REG_MODE_CONFIG, MAX30102_MODE_RESET);
    HAL_Delay(10U);
    (void)Max30102_ReadReg(MAX30102_REG_INTR_STATUS_1, &dummy);
    (void)Max30102_ReadReg(MAX30102_REG_INTR_STATUS_2, &dummy);

    if ((Max30102_WriteReg(MAX30102_REG_INTR_ENABLE_1, 0x00U) != HAL_OK) ||
        (Max30102_WriteReg(MAX30102_REG_INTR_ENABLE_2, 0x00U) != HAL_OK) ||
        (Max30102_WriteReg(MAX30102_REG_FIFO_WR_PTR, 0x00U) != HAL_OK) ||
        (Max30102_WriteReg(MAX30102_REG_OVF_COUNTER, 0x00U) != HAL_OK) ||
        (Max30102_WriteReg(MAX30102_REG_FIFO_RD_PTR, 0x00U) != HAL_OK) ||
        (Max30102_WriteReg(MAX30102_REG_FIFO_CONFIG,
                           MAX30102_FIFO_ROLLOVER_EN | MAX30102_FIFO_ALMOST_FULL) != HAL_OK) ||
        (Max30102_WriteReg(MAX30102_REG_SPO2_CONFIG,
                           MAX30102_SPO2_ADC_16384 |
                           MAX30102_SPO2_SR_100HZ |
                           MAX30102_SPO2_PW_411US) != HAL_OK) ||
        (Max30102_WriteReg(MAX30102_REG_LED1_PA, 0x7FU) != HAL_OK) ||
        (Max30102_WriteReg(MAX30102_REG_LED2_PA, 0x7FU) != HAL_OK) ||
        (Max30102_WriteReg(MAX30102_REG_MODE_CONFIG, MAX30102_MODE_SPO2) != HAL_OK)) {
        g_max30102.state.i2c_error_count++;
        return 0U;
    }

    g_max30102.state.initialized = 1U;
    return 1U;
}

void Max30102Spo2_Service(void)
{
    const uint32_t now = HAL_GetTick();

    if ((g_max30102.state.initialized == 0U) || (g_max30102.hi2c == NULL)) {
        Max30102_UpdateStatusLed();
        return;
    }

    if ((now - g_max30102.last_poll_tick) >= MAX30102_POLL_MS) {
        g_max30102.last_poll_tick = now;
        Max30102_PollFifo();
    }

    Max30102_UpdateStatusLed();
}

void Max30102Spo2_GetState(Max30102Spo2State *out_state)
{
    if (out_state != NULL) {
        *out_state = g_max30102.state;
    }
}
