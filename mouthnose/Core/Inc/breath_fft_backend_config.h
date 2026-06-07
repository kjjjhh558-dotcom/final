/*
 * 파일 설명:
 *   STM32 DSP feature extractor에서 사용할 FFT backend를 선택합니다.
 *   내부 radix-2 FFT와 CMSIS-DSP RFFT 중 하나를 고르며, 현재 기본값은 CMSIS-DSP입니다.
 */

#ifndef BREATH_FFT_BACKEND_CONFIG_H
#define BREATH_FFT_BACKEND_CONFIG_H

/* FFT backend selector for the STM32 TinyML feature extractor.
 *
 * BREATH_FFT_BACKEND_INTERNAL uses the local radix-2 FFT already validated on
 * the board. BREATH_FFT_BACKEND_CMSIS_DSP uses ARM CMSIS-DSP RFFT and links the
 * minimal CMSIS-DSP source bundle from Core/Src/cmsis_dsp_bundle.c.
 */
#define BREATH_FFT_BACKEND_INTERNAL 0
#define BREATH_FFT_BACKEND_CMSIS_DSP 1

#ifndef BREATH_FFT_BACKEND
#define BREATH_FFT_BACKEND BREATH_FFT_BACKEND_CMSIS_DSP
#endif

#endif /* BREATH_FFT_BACKEND_CONFIG_H */
