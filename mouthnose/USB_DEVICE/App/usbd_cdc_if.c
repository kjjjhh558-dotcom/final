/* USER CODE BEGIN Header */
/* 파일 설명: USB CDC 가상 COM 포트 송수신과 PC에서 전달하는 AI ON/OFF 텍스트 명령을 처리합니다. */
/**
  ******************************************************************************
  * @file           : usbd_cdc_if.c
  * @version        : v1.0_Cube
  * @brief          : Usb device for Virtual Com Port.
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

/* Includes ------------------------------------------------------------------*/
#include "usbd_cdc_if.h"

/* USER CODE BEGIN INCLUDE */
#include <string.h>
#include "breath_ai_app.h"
#include "main.h"
/* USER CODE END INCLUDE */

/* Private typedef -----------------------------------------------------------*/
/* Private define ------------------------------------------------------------*/
/* Private macro -------------------------------------------------------------*/

/* USER CODE BEGIN PV */
/* Private variables ---------------------------------------------------------*/

/* USER CODE END PV */

/** @addtogroup STM32_USB_OTG_DEVICE_LIBRARY
  * @brief Usb device library.
  * @{
  */

/** @addtogroup USBD_CDC_IF
  * @{
  */

/** @defgroup USBD_CDC_IF_Private_TypesDefinitions USBD_CDC_IF_Private_TypesDefinitions
  * @brief Private types.
  * @{
  */

/* USER CODE BEGIN PRIVATE_TYPES */

/* USER CODE END PRIVATE_TYPES */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Private_Defines USBD_CDC_IF_Private_Defines
  * @brief Private defines.
  * @{
  */

/* USER CODE BEGIN PRIVATE_DEFINES */
/* USER CODE END PRIVATE_DEFINES */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Private_Macros USBD_CDC_IF_Private_Macros
  * @brief Private macros.
  * @{
  */

/* USER CODE BEGIN PRIVATE_MACRO */

/* USER CODE END PRIVATE_MACRO */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Private_Variables USBD_CDC_IF_Private_Variables
  * @brief Private variables.
  * @{
  */
/* Create buffer for reception and transmission           */
/* It's up to user to redefine and/or remove those define */
/** Received data over USB are stored in this buffer      */
uint8_t UserRxBufferFS[APP_RX_DATA_SIZE];

/** Data to send over USB CDC are stored in this buffer   */
uint8_t UserTxBufferFS[APP_TX_DATA_SIZE];

/* USER CODE BEGIN PRIVATE_VARIABLES */

/* USER CODE END PRIVATE_VARIABLES */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Exported_Variables USBD_CDC_IF_Exported_Variables
  * @brief Public variables.
  * @{
  */

extern USBD_HandleTypeDef hUsbDeviceFS;

/* USER CODE BEGIN EXPORTED_VARIABLES */

/* USER CODE END EXPORTED_VARIABLES */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Private_FunctionPrototypes USBD_CDC_IF_Private_FunctionPrototypes
  * @brief Private functions declaration.
  * @{
  */

/* 함수 설명: USB CDC FS 인터페이스 수신 버퍼를 연결하고 초기화합니다. */
static int8_t CDC_Init_FS(void);
/* 함수 설명: USB CDC FS 인터페이스 종료 시 필요한 정리를 수행합니다. */
static int8_t CDC_DeInit_FS(void);
/* 함수 설명: USB CDC class-specific control 요청을 처리하는 콜백입니다. */
static int8_t CDC_Control_FS(uint8_t cmd, uint8_t* pbuf, uint16_t length);
/* 함수 설명: PC에서 수신한 USB CDC 데이터를 명령 파서로 넘기고 다음 수신을 준비합니다. */
static int8_t CDC_Receive_FS(uint8_t* pbuf, uint32_t *Len);
/* 함수 설명: USB CDC 전송 완료 후 busy 플래그를 해제합니다. */
static int8_t CDC_TransmitCplt_FS(uint8_t *pbuf, uint32_t *Len, uint8_t epnum);

/* USER CODE BEGIN PRIVATE_FUNCTIONS_DECLARATION */
/* 함수 설명: PC에서 들어온 텍스트를 해석해 STM AI 실시간 추론을 켜거나 끕니다. */
static void CDC_ProcessTextCommand(uint8_t *buf, uint32_t len);
static uint8_t CDC_ParseCommandValue(const char *command, const char *prefix, uint32_t *value);
static uint32_t CDC_NormalizeDutyValue(uint32_t value);
/* USER CODE END PRIVATE_FUNCTIONS_DECLARATION */

/**
  * @}
  */

USBD_CDC_ItfTypeDef USBD_Interface_fops_FS =
{
  CDC_Init_FS,
  CDC_DeInit_FS,
  CDC_Control_FS,
  CDC_Receive_FS,
  CDC_TransmitCplt_FS
};

/* Private functions ---------------------------------------------------------*/
/**
  * @brief  Initializes the CDC media low layer over the FS USB IP
  * @retval USBD_OK if all operations are OK else USBD_FAIL
  */
/* 함수 설명: USB CDC FS 인터페이스 수신 버퍼를 연결하고 초기화합니다. */
static int8_t CDC_Init_FS(void)
{
  /* USER CODE BEGIN 3 */
  /* Set Application Buffers */
  USBD_CDC_SetTxBuffer(&hUsbDeviceFS, UserTxBufferFS, 0);
  USBD_CDC_SetRxBuffer(&hUsbDeviceFS, UserRxBufferFS);
  return (USBD_OK);
  /* USER CODE END 3 */
}

/**
  * @brief  DeInitializes the CDC media low layer
  * @retval USBD_OK if all operations are OK else USBD_FAIL
  */
/* 함수 설명: USB CDC FS 인터페이스 종료 시 필요한 정리를 수행합니다. */
static int8_t CDC_DeInit_FS(void)
{
  /* USER CODE BEGIN 4 */
  return (USBD_OK);
  /* USER CODE END 4 */
}

/**
  * @brief  Manage the CDC class requests
  * @param  cmd: Command code
  * @param  pbuf: Buffer containing command data (request parameters)
  * @param  length: Number of data to be sent (in bytes)
  * @retval Result of the operation: USBD_OK if all operations are OK else USBD_FAIL
  */
/* 함수 설명: USB CDC class-specific control 요청을 처리하는 콜백입니다. */
static int8_t CDC_Control_FS(uint8_t cmd, uint8_t* pbuf, uint16_t length)
{
  /* USER CODE BEGIN 5 */
  switch(cmd)
  {
    case CDC_SEND_ENCAPSULATED_COMMAND:

    break;

    case CDC_GET_ENCAPSULATED_RESPONSE:

    break;

    case CDC_SET_COMM_FEATURE:

    break;

    case CDC_GET_COMM_FEATURE:

    break;

    case CDC_CLEAR_COMM_FEATURE:

    break;

  /*******************************************************************************/
  /* Line Coding Structure                                                       */
  /*-----------------------------------------------------------------------------*/
  /* Offset | Field       | Size | Value  | Description                          */
  /* 0      | dwDTERate   |   4  | Number |Data terminal rate, in bits per second*/
  /* 4      | bCharFormat |   1  | Number | Stop bits                            */
  /*                                        0 - 1 Stop bit                       */
  /*                                        1 - 1.5 Stop bits                    */
  /*                                        2 - 2 Stop bits                      */
  /* 5      | bParityType |  1   | Number | Parity                               */
  /*                                        0 - None                             */
  /*                                        1 - Odd                              */
  /*                                        2 - Even                             */
  /*                                        3 - Mark                             */
  /*                                        4 - Space                            */
  /* 6      | bDataBits  |   1   | Number Data bits (5, 6, 7, 8 or 16).          */
  /*******************************************************************************/
    case CDC_SET_LINE_CODING:

    break;

    case CDC_GET_LINE_CODING:

    break;

    case CDC_SET_CONTROL_LINE_STATE:

    break;

    case CDC_SEND_BREAK:

    break;

  default:
    break;
  }

  return (USBD_OK);
  /* USER CODE END 5 */
}

/**
  * @brief  Data received over USB OUT endpoint are sent over CDC interface
  *         through this function.
  *
  *         @note
  *         This function will issue a NAK packet on any OUT packet received on
  *         USB endpoint until exiting this function. If you exit this function
  *         before transfer is complete on CDC interface (ie. using DMA controller)
  *         it will result in receiving more data while previous ones are still
  *         not sent.
  *
  * @param  Buf: Buffer of data to be received
  * @param  Len: Number of data received (in bytes)
  * @retval Result of the operation: USBD_OK if all operations are OK else USBD_FAIL
  */
/* 함수 설명: PC에서 수신한 USB CDC 데이터를 명령 파서로 넘기고 다음 수신을 준비합니다. */
static int8_t CDC_Receive_FS(uint8_t* Buf, uint32_t *Len)
{
  /* USER CODE BEGIN 6 */
  CDC_ProcessTextCommand(Buf, *Len);
  USBD_CDC_SetRxBuffer(&hUsbDeviceFS, &Buf[0]);
  USBD_CDC_ReceivePacket(&hUsbDeviceFS);
  return (USBD_OK);
  /* USER CODE END 6 */
}

/**
  * @brief  CDC_Transmit_FS
  *         Data to send over USB IN endpoint are sent over CDC interface
  *         through this function.
  *         @note
  *
  *
  * @param  Buf: Buffer of data to be sent
  * @param  Len: Number of data to be sent (in bytes)
  * @retval USBD_OK if all operations are OK else USBD_FAIL or USBD_BUSY
  */
/* 함수 설명: 상위 코드가 요청한 버퍼를 USB CDC IN endpoint로 전송합니다. */
uint8_t CDC_Transmit_FS(uint8_t* Buf, uint16_t Len)
{
  uint8_t result = USBD_OK;
  /* USER CODE BEGIN 7 */
  USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef*)hUsbDeviceFS.pClassData;
  if (hcdc->TxState != 0){
    return USBD_BUSY;
  }
  USBD_CDC_SetTxBuffer(&hUsbDeviceFS, Buf, Len);
  result = USBD_CDC_TransmitPacket(&hUsbDeviceFS);
  /* USER CODE END 7 */
  return result;
}

/**
  * @brief  CDC_TransmitCplt_FS
  *         Data transmitted callback
  *
  *         @note
  *         This function is IN transfer complete callback used to inform user that
  *         the submitted Data is successfully sent over USB.
  *
  * @param  Buf: Buffer of data to be received
  * @param  Len: Number of data received (in bytes)
  * @retval Result of the operation: USBD_OK if all operations are OK else USBD_FAIL
  */
/* 함수 설명: USB CDC 전송 완료 후 busy 플래그를 해제합니다. */
static int8_t CDC_TransmitCplt_FS(uint8_t *Buf, uint32_t *Len, uint8_t epnum)
{
  uint8_t result = USBD_OK;
  /* USER CODE BEGIN 13 */
  UNUSED(Buf);
  UNUSED(Len);
  UNUSED(epnum);
  /* USER CODE END 13 */
  return result;
}

/* USER CODE BEGIN PRIVATE_FUNCTIONS_IMPLEMENTATION */

/* 함수 설명: PC에서 들어온 텍스트를 해석해 STM AI 실시간 추론을 켜거나 끕니다. */
static uint8_t CDC_ParseCommandValue(const char *command, const char *prefix, uint32_t *value)
{
  size_t prefix_len;
  uint32_t parsed = 0U;
  uint8_t saw_digit = 0U;

  if ((command == NULL) || (prefix == NULL) || (value == NULL)) {
    return 0U;
  }

  prefix_len = strlen(prefix);
  if (strncmp(command, prefix, prefix_len) != 0) {
    return 0U;
  }

  command += prefix_len;
  while ((*command == ' ') || (*command == '=')) {
    command++;
  }

  while ((*command >= '0') && (*command <= '9')) {
    saw_digit = 1U;
    parsed = (parsed * 10U) + (uint32_t)(*command - '0');
    command++;
  }

  if (saw_digit == 0U) {
    return 0U;
  }

  *value = parsed;
  return 1U;
}

static uint32_t CDC_NormalizeDutyValue(uint32_t value)
{
  if (value <= 100U) {
    return value * 10U;
  }

  if (value > 1000U) {
    return 1000U;
  }

  return value;
}

static void CDC_ProcessTextCommand(uint8_t *buf, uint32_t len)
{
  char command[24];
  uint32_t out = 0U;
  uint32_t value = 0U;

  if (buf == NULL) {
    return;
  }

  for (uint32_t i = 0U; (i < len) && (out < (sizeof(command) - 1U)); ++i) {
    char ch = (char)buf[i];

    if ((ch == '\r') || (ch == '\n') || (ch == '\0')) {
      break;
    }

    if ((ch >= 'a') && (ch <= 'z')) {
      ch = (char)(ch - ('a' - 'A'));
    }

    command[out++] = ch;
  }

  command[out] = '\0';

  if ((strcmp(command, "AI ON") == 0) ||
      (strcmp(command, "AI=ON") == 0) ||
      (strcmp(command, "AI_ON") == 0)) {
    BreathAI_SetLiveInferenceEnabled(1U);
    return;
  }

  if ((strcmp(command, "AI OFF") == 0) ||
      (strcmp(command, "AI=OFF") == 0) ||
      (strcmp(command, "AI_OFF") == 0)) {
    BreathAI_SetLiveInferenceEnabled(0U);
    BreathActuator_Off();
    return;
  }

  if ((strcmp(command, "LED STABLE") == 0) ||
      (strcmp(command, "LED=STABLE") == 0) ||
      (strcmp(command, "LED_STABLE") == 0) ||
      (strcmp(command, "LED POST") == 0) ||
      (strcmp(command, "LED=POST") == 0) ||
      (strcmp(command, "LED_POST") == 0)) {
    BreathLed_SetMode(BREATH_LED_MODE_STABLE);
    return;
  }

  if ((strcmp(command, "LED RAW") == 0) ||
      (strcmp(command, "LED=RAW") == 0) ||
      (strcmp(command, "LED_RAW") == 0)) {
    BreathLed_SetMode(BREATH_LED_MODE_RAW);
    return;
  }

  if ((strcmp(command, "LED OFF") == 0) ||
      (strcmp(command, "LED=OFF") == 0) ||
      (strcmp(command, "LED_OFF") == 0)) {
    BreathLed_SetMode(BREATH_LED_MODE_OFF);
    return;
  }

  if ((strcmp(command, "LED TEST OFF") == 0) ||
      (strcmp(command, "LEDTEST OFF") == 0)) {
    BreathLed_TestOff();
    return;
  }

  if ((strcmp(command, "LED TEST ALL") == 0) ||
      (strcmp(command, "LEDTEST ALL") == 0)) {
    BreathLed_TestAll();
    return;
  }

  if ((strcmp(command, "LED TEST PUMP") == 0) ||
      (strcmp(command, "LED TEST PE5") == 0) ||
      (strcmp(command, "LEDTEST PUMP") == 0) ||
      (strcmp(command, "LEDTEST PE5") == 0)) {
    BreathLed_TestPumpIndicator();
    return;
  }

  if ((strcmp(command, "LED TEST NOISE") == 0) ||
      (strcmp(command, "LED TEST PE7") == 0) ||
      (strcmp(command, "LEDTEST NOISE") == 0) ||
      (strcmp(command, "LEDTEST PE7") == 0)) {
    BreathLed_TestClass(4U);
    return;
  }

  if (CDC_ParseCommandValue(command, "LED TEST", &value) ||
      CDC_ParseCommandValue(command, "LEDTEST", &value)) {
    if (value <= 4U) {
      BreathLed_TestClass(value);
    } else if (value == 5U) {
      BreathLed_TestPumpIndicator();
    }
    return;
  }

  if ((strcmp(command, "PLED ON") == 0) ||
      (strcmp(command, "PLED=ON") == 0) ||
      (strcmp(command, "PLED_ON") == 0) ||
      (strcmp(command, "PUMPLED ON") == 0) ||
      (strcmp(command, "PUMPLED=ON") == 0) ||
      (strcmp(command, "PUMPLED_ON") == 0) ||
      (strcmp(command, "PUMP LED ON") == 0)) {
    BreathPumpLed_SetEnabled(1U);
    return;
  }

  if ((strcmp(command, "PLED OFF") == 0) ||
      (strcmp(command, "PLED=OFF") == 0) ||
      (strcmp(command, "PLED_OFF") == 0) ||
      (strcmp(command, "PUMPLED OFF") == 0) ||
      (strcmp(command, "PUMPLED=OFF") == 0) ||
      (strcmp(command, "PUMPLED_OFF") == 0) ||
      (strcmp(command, "PUMP LED OFF") == 0)) {
    BreathPumpLed_SetEnabled(0U);
    return;
  }

  if ((strcmp(command, "OUT") == 0) ||
      (strcmp(command, "AIR OUT") == 0) ||
      (strcmp(command, "AIRBAG OUT") == 0) ||
      (strcmp(command, "VENT") == 0) ||
      (strcmp(command, "EXHAUST") == 0)) {
    OralAirValve_ManualOn();
    return;
  }

  if ((strcmp(command, "ACT AI ON") == 0) ||
      (strcmp(command, "PUMP AI ON") == 0)) {
    BreathActuator_SetAiControlEnabled(1U);
    return;
  }

  if ((strcmp(command, "ACT AI OFF") == 0) ||
      (strcmp(command, "PUMP AI OFF") == 0) ||
      (strcmp(command, "ACT OFF") == 0) ||
      (strcmp(command, "PUMP OFF") == 0) ||
      (strcmp(command, "ACT STOP") == 0) ||
      (strcmp(command, "PUMP STOP") == 0) ||
      (strcmp(command, "STOP") == 0) ||
      (strcmp(command, "CLOSE") == 0) ||
      (strcmp(command, "AIRBAG CLOSE") == 0)) {
    BreathActuator_Off();
    return;
  }

  if ((strcmp(command, "ACT TEST") == 0) ||
      (strcmp(command, "PUMP TEST") == 0)) {
    BreathActuator_ManualPulse(BreathActuator_GetDutyPermille(), 0U);
    return;
  }

  if (CDC_ParseCommandValue(command, "ACT TEST", &value) ||
      CDC_ParseCommandValue(command, "PUMP TEST", &value)) {
    BreathActuator_ManualPulse(CDC_NormalizeDutyValue(value), 0U);
    return;
  }

  if (CDC_ParseCommandValue(command, "ACT ON", &value) ||
      CDC_ParseCommandValue(command, "PUMP ON", &value)) {
    BreathActuator_ManualOn(CDC_NormalizeDutyValue(value));
    return;
  }

  if ((strcmp(command, "ACT ON") == 0) ||
      (strcmp(command, "PUMP ON") == 0)) {
    BreathActuator_ManualOn(BreathActuator_GetDutyPermille());
    return;
  }

  if (CDC_ParseCommandValue(command, "ACT DUTY", &value) ||
      CDC_ParseCommandValue(command, "PUMP DUTY", &value) ||
      CDC_ParseCommandValue(command, "ACT=", &value) ||
      CDC_ParseCommandValue(command, "PUMP=", &value)) {
    BreathActuator_SetDutyPermille(CDC_NormalizeDutyValue(value));
    return;
  }

  if ((strcmp(command, "VALVE ON") == 0) ||
      (strcmp(command, "VALVE=ON") == 0) ||
      (strcmp(command, "VALVE_ON") == 0) ||
      (strcmp(command, "ORAL VALVE ON") == 0)) {
    OralAirValve_ManualOn();
    return;
  }

  if ((strcmp(command, "VALVE OFF") == 0) ||
      (strcmp(command, "VALVE=OFF") == 0) ||
      (strcmp(command, "VALVE_OFF") == 0) ||
      (strcmp(command, "ORAL VALVE OFF") == 0)) {
    OralAirValve_ManualOff();
    return;
  }

  if ((strcmp(command, "VALVE TEST") == 0) ||
      (strcmp(command, "ORAL VALVE TEST") == 0)) {
    OralAirValve_ManualPulse(0U);
    return;
  }

  if (CDC_ParseCommandValue(command, "VALVE TEST", &value) ||
      CDC_ParseCommandValue(command, "ORAL VALVE TEST", &value)) {
    OralAirValve_ManualPulse(value);
    return;
  }

  if ((strcmp(command, "MAX ON") == 0) ||
      (strcmp(command, "MAX=ON") == 0) ||
      (strcmp(command, "MAX_ON") == 0) ||
      (strcmp(command, "MAX30102 ON") == 0) ||
      (strcmp(command, "MAX TELEMETRY ON") == 0)) {
    Max30102Telemetry_SetEnabled(1U);
    return;
  }

  if ((strcmp(command, "MAX OFF") == 0) ||
      (strcmp(command, "MAX=OFF") == 0) ||
      (strcmp(command, "MAX_OFF") == 0) ||
      (strcmp(command, "MAX30102 OFF") == 0) ||
      (strcmp(command, "MAX TELEMETRY OFF") == 0)) {
    Max30102Telemetry_SetEnabled(0U);
    return;
  }

  if ((strcmp(command, "IMU ON") == 0) ||
      (strcmp(command, "IMU=ON") == 0) ||
      (strcmp(command, "IMU_ON") == 0) ||
      (strcmp(command, "IMU TELEMETRY ON") == 0)) {
    ImuBridgeTelemetry_SetEnabled(1U);
    return;
  }

  if ((strcmp(command, "IMU OFF") == 0) ||
      (strcmp(command, "IMU=OFF") == 0) ||
      (strcmp(command, "IMU_OFF") == 0) ||
      (strcmp(command, "IMU TELEMETRY OFF") == 0)) {
    ImuBridgeTelemetry_SetEnabled(0U);
    return;
  }

  if ((strcmp(command, "IMU RESET") == 0) ||
      (strcmp(command, "IMU COUNTER RESET") == 0) ||
      (strcmp(command, "IMU TELEMETRY RESET") == 0)) {
    ImuBridgeTelemetry_ResetCounters();
    return;
  }
}

/* USER CODE END PRIVATE_FUNCTIONS_IMPLEMENTATION */

/**
  * @}
  */

/**
  * @}
  */
