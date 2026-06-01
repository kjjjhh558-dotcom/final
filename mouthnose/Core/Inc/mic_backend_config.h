/* USER CODE BEGIN Header */
/*
 * 마이크 입력 backend 선택 설정입니다.
 *
 * 기본값은 기존 MAX9814 ADC 경로입니다.
 * ICS-43434 I2S 마이크를 테스트할 때만 MIC_BACKEND를
 * MIC_BACKEND_I2S_ICS43434로 바꿔서 빌드합니다.
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
