#ifndef MAX30102_SPO2_H
#define MAX30102_SPO2_H

#include <stdint.h>
#include "stm32f4xx_hal.h"

typedef enum {
    MAX30102_SPO2_STATUS_OFF = 0,
    MAX30102_SPO2_STATUS_NORMAL,
    MAX30102_SPO2_STATUS_ABNORMAL
} Max30102Spo2Status;

typedef struct {
    uint8_t initialized;
    uint8_t present;
    uint8_t finger_detected;
    uint8_t spo2_ok;
    uint8_t part_id;
    int32_t ir;
    int32_t red;
    int32_t heart_rate_bpm;
    int32_t spo2_percent;
    float ratio;
    Max30102Spo2Status status;
    uint32_t sample_count;
    uint32_t i2c_error_count;
} Max30102Spo2State;

uint8_t Max30102Spo2_Init(I2C_HandleTypeDef *hi2c, GPIO_TypeDef *led_port, uint16_t led_pin);
void Max30102Spo2_Service(void);
void Max30102Spo2_GetState(Max30102Spo2State *out_state);

#endif /* MAX30102_SPO2_H */
