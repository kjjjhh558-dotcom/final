/* USER CODE BEGIN Header */
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
void Error_Handler(void);

/* USER CODE BEGIN EFP */
#define BREATH_LED_MODE_STABLE 0U
#define BREATH_LED_MODE_RAW    1U
#define BREATH_LED_MODE_OFF    2U

void BreathLed_SetMode(uint32_t mode);
uint32_t BreathLed_GetMode(void);
void BreathLed_TestClass(uint32_t class_index);
void BreathLed_TestPumpIndicator(void);
void BreathLed_TestAll(void);
void BreathLed_TestOff(void);

void BreathPumpLed_SetEnabled(uint32_t enabled);
uint32_t BreathPumpLed_IsEnabled(void);
uint32_t BreathPumpLed_IsActive(void);

void BreathActuator_SetAiControlEnabled(uint32_t enabled);
uint32_t BreathActuator_IsAiControlEnabled(void);
void BreathActuator_SetDutyPermille(uint32_t duty_permille);
uint32_t BreathActuator_GetDutyPermille(void);
void BreathActuator_ManualOn(uint32_t duty_permille);
void BreathActuator_ManualPulse(uint32_t duty_permille, uint32_t duration_ms);
void BreathActuator_Off(void);

void OralAirValve_ManualOn(void);
void OralAirValve_ManualOff(void);
void OralAirValve_ManualPulse(uint32_t duration_ms);
uint32_t OralAirValve_IsActive(void);

void ImuBridgeTelemetry_SetEnabled(uint32_t enabled);
uint32_t ImuBridgeTelemetry_IsEnabled(void);
void ImuBridgeTelemetry_ResetCounters(void);

void Max30102Telemetry_SetEnabled(uint32_t enabled);
uint32_t Max30102Telemetry_IsEnabled(void);

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
