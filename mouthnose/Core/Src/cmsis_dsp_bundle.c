#include "breath_fft_backend_config.h"

#if BREATH_FFT_BACKEND == BREATH_FFT_BACKEND_CMSIS_DSP

/* Keep CMSIS-DSP optional and local to this project. CubeIDE builds Core/Src
 * automatically, so this wrapper pulls in only the RFFT-related C sources
 * needed by breath_features.c when the CMSIS backend is enabled.
 */
#ifndef ARM_MATH_CM4
#define ARM_MATH_CM4
#endif

#include "arm_common_tables.c"
#include "arm_const_structs.c"
#include "arm_bitreversal.c"
#include "arm_bitreversal2.c"
#include "arm_cfft_radix8_f32.c"
#include "arm_cfft_init_f32.c"
#include "arm_cfft_f32.c"
#include "arm_rfft_fast_init_f32.c"
#include "arm_rfft_fast_f32.c"

#endif /* BREATH_FFT_BACKEND == BREATH_FFT_BACKEND_CMSIS_DSP */
