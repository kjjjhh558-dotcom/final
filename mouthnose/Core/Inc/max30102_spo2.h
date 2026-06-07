/*
 * 파일 설명:
 *   MAX30102 산소포화도/심박 상태 구조와 초기화/서비스/상태 조회 API를 선언합니다.
 */

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

/* 함수 설명: I2C 핸들과 상태 LED 핀을 저장하고 MAX30102 레지스터를 SpO2 모드로 설정합니다. */
uint8_t Max30102Spo2_Init(I2C_HandleTypeDef *hi2c, GPIO_TypeDef *led_port, uint16_t led_pin);
/* 함수 설명: 주기적으로 FIFO를 읽고 심박/SpO2 상태와 상태 LED를 갱신합니다. */
void Max30102Spo2_Service(void);
/* 함수 설명: 현재 MAX30102 runtime state snapshot을 호출자 버퍼로 복사합니다. */
void Max30102Spo2_GetState(Max30102Spo2State *out_state);

#endif /* MAX30102_SPO2_H */
