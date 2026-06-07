/* USER CODE BEGIN Header */
/* 파일 설명: main.c가 외부 모듈과 USB CDC 명령 처리부에 공개하는 LED, 펌프, 밸브, IMU/MAX30102 제어 API를 선언합니다. */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f4xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
/* 함수 설명: Error_Handler는 치명적 초기화/런타임 오류 발생 시 interrupt를 막고 무한 대기합니다. */
void Error_Handler(void);

/* USER CODE BEGIN EFP */
#define BREATH_LED_MODE_STABLE 0U
#define BREATH_LED_MODE_RAW    1U
#define BREATH_LED_MODE_OFF    2U

/* 함수 설명: BreathLed_SetMode는 AI 라벨 표시용 클래스 LED 상태를 설정하거나 주기적으로 갱신합니다. */
void BreathLed_SetMode(uint32_t mode);
/* 함수 설명: BreathLed_GetMode는 AI 라벨 표시용 클래스 LED 상태를 설정하거나 주기적으로 갱신합니다. */
uint32_t BreathLed_GetMode(void);
/* 함수 설명: BreathLed_TestClass는 AI 라벨 표시용 클래스 LED 상태를 설정하거나 주기적으로 갱신합니다. */
void BreathLed_TestClass(uint32_t class_index);
/* 함수 설명: BreathLed_TestPumpIndicator는 AI 라벨 표시용 클래스 LED 상태를 설정하거나 주기적으로 갱신합니다. */
void BreathLed_TestPumpIndicator(void);
/* 함수 설명: BreathLed_TestAll는 AI 라벨 표시용 클래스 LED 상태를 설정하거나 주기적으로 갱신합니다. */
void BreathLed_TestAll(void);
/* 함수 설명: BreathLed_TestOff는 AI 라벨 표시용 클래스 LED 상태를 설정하거나 주기적으로 갱신합니다. */
void BreathLed_TestOff(void);

/* 함수 설명: BreathPumpLed_SetEnabled는 mouth 계열 예측에 따른 펌프 동작 표시 LED 정책을 관리합니다. */
void BreathPumpLed_SetEnabled(uint32_t enabled);
/* 함수 설명: BreathPumpLed_IsEnabled는 mouth 계열 예측에 따른 펌프 동작 표시 LED 정책을 관리합니다. */
uint32_t BreathPumpLed_IsEnabled(void);
/* 함수 설명: BreathPumpLed_IsActive는 mouth 계열 예측에 따른 펌프 동작 표시 LED 정책을 관리합니다. */
uint32_t BreathPumpLed_IsActive(void);

/* 함수 설명: BreathActuator_SetAiControlEnabled는 PA6/PA7 PWM 펌프 출력의 duty, 시작, 정지, 안전 제한을 관리합니다. */
void BreathActuator_SetAiControlEnabled(uint32_t enabled);
/* 함수 설명: BreathActuator_IsAiControlEnabled는 PA6/PA7 PWM 펌프 출력의 duty, 시작, 정지, 안전 제한을 관리합니다. */
uint32_t BreathActuator_IsAiControlEnabled(void);
/* 함수 설명: BreathActuator_SetDutyPermille는 PA6/PA7 PWM 펌프 출력의 duty, 시작, 정지, 안전 제한을 관리합니다. */
void BreathActuator_SetDutyPermille(uint32_t duty_permille);
/* 함수 설명: BreathActuator_GetDutyPermille는 PA6/PA7 PWM 펌프 출력의 duty, 시작, 정지, 안전 제한을 관리합니다. */
uint32_t BreathActuator_GetDutyPermille(void);
/* 함수 설명: BreathActuator_ManualOn는 PA6/PA7 PWM 펌프 출력의 duty, 시작, 정지, 안전 제한을 관리합니다. */
void BreathActuator_ManualOn(uint32_t duty_permille);
/* 함수 설명: BreathActuator_ManualPulse는 PA6/PA7 PWM 펌프 출력의 duty, 시작, 정지, 안전 제한을 관리합니다. */
void BreathActuator_ManualPulse(uint32_t duty_permille, uint32_t duration_ms);
/* 함수 설명: BreathActuator_Off는 PA6/PA7 PWM 펌프 출력의 duty, 시작, 정지, 안전 제한을 관리합니다. */
void BreathActuator_Off(void);

/* 함수 설명: OralAirValve_ManualOn는 구강/사이드 에어백 밸브와 펌프 시퀀스를 제어합니다. */
void OralAirValve_ManualOn(void);
/* 함수 설명: OralAirValve_ManualOff는 구강/사이드 에어백 밸브와 펌프 시퀀스를 제어합니다. */
void OralAirValve_ManualOff(void);
/* 함수 설명: OralAirValve_ManualPulse는 구강/사이드 에어백 밸브와 펌프 시퀀스를 제어합니다. */
void OralAirValve_ManualPulse(uint32_t duration_ms);
/* 함수 설명: OralAirValve_IsActive는 구강/사이드 에어백 밸브와 펌프 시퀀스를 제어합니다. */
uint32_t OralAirValve_IsActive(void);

/* 함수 설명: ImuBridgeTelemetry_SetEnabled는 ESP32-S3에서 들어오는 IMU 자세 토큰을 파싱하고 STM32 제어 상태로 반영합니다. */
void ImuBridgeTelemetry_SetEnabled(uint32_t enabled);
/* 함수 설명: ImuBridgeTelemetry_IsEnabled는 ESP32-S3에서 들어오는 IMU 자세 토큰을 파싱하고 STM32 제어 상태로 반영합니다. */
uint32_t ImuBridgeTelemetry_IsEnabled(void);
/* 함수 설명: ImuBridgeTelemetry_ResetCounters는 ESP32-S3에서 들어오는 IMU 자세 토큰을 파싱하고 STM32 제어 상태로 반영합니다. */
void ImuBridgeTelemetry_ResetCounters(void);

/* 함수 설명: Max30102Telemetry_SetEnabled는 MAX30102 센서 초기화, sample 처리, 텔레메트리 상태 갱신을 담당합니다. */
void Max30102Telemetry_SetEnabled(uint32_t enabled);
/* 함수 설명: Max30102Telemetry_IsEnabled는 MAX30102 센서 초기화, sample 처리, 텔레메트리 상태 갱신을 담당합니다. */
uint32_t Max30102Telemetry_IsEnabled(void);

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
