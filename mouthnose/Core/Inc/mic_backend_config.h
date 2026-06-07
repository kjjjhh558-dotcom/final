/* USER CODE BEGIN Header */
/*
 * 파일 설명:
 *   마이크 입력 backend를 선택하는 설정 파일입니다.
 *   MIC_BACKEND_ADC_MAX9814는 ADC 마이크 경로, MIC_BACKEND_I2S_ICS43434는 ICS-43434 I2S 디지털 마이크 경로입니다.
 *   현재 기본값은 ICS-43434 I2S 경로입니다.
 */
/* USER CODE END Header */

#ifndef MIC_BACKEND_CONFIG_H
#define MIC_BACKEND_CONFIG_H

#define MIC_BACKEND_ADC_MAX9814    0
#define MIC_BACKEND_I2S_ICS43434   1

#ifndef MIC_BACKEND
//#define MIC_BACKEND MIC_BACKEND_ADC_MAX9814
#define MIC_BACKEND MIC_BACKEND_I2S_ICS43434
#endif

#if (MIC_BACKEND != MIC_BACKEND_ADC_MAX9814) && (MIC_BACKEND != MIC_BACKEND_I2S_ICS43434)
#error "Invalid MIC_BACKEND selection"
#endif

#endif /* MIC_BACKEND_CONFIG_H */
