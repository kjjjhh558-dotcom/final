# -*- coding: utf-8 -*-
"""Report the active STM32 firmware/model configuration from source files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(read_text(path))


def active_define(text: str, name: str) -> str | None:
    pattern = re.compile(rf"^\s*#define\s+{re.escape(name)}\s+(.+?)\s*$", re.MULTILINE)
    for match in pattern.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start:match.start()]
        if "//" in prefix or prefix.strip().startswith("/*"):
            continue
        return match.group(1).strip()
    return None


def c_initializer(text: str, name: str) -> str | None:
    pattern = re.compile(rf"\b{name}\s*=\s*([^;]+);")
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def macro_float(text: str, name: str) -> float | None:
    value = active_define(text, name)
    if value is None:
        return None
    try:
        return float(value.rstrip("fFuUlL"))
    except ValueError:
        return None


def macro_int(text: str, name: str) -> int | None:
    value = active_define(text, name)
    if value is None:
        return None
    try:
        return int(value.rstrip("uUlL"), 0)
    except ValueError:
        return None


def fmt_bool(value: str | None) -> str:
    if value is None:
        return "unknown"
    if value in {"1U", "1", "true"}:
        return "ON"
    if value in {"0U", "0", "false"}:
        return "OFF"
    return value


def led_mode_name(value: str | None) -> str:
    mapping = {
        "BREATH_LED_MODE_STABLE": "STABLE/post-processed",
        "BREATH_LED_MODE_RAW": "RAW argmax",
        "BREATH_LED_MODE_OFF": "OFF",
    }
    return mapping.get(value or "", value or "unknown")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read firmware source files and print active model/board settings.")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    root = args.root.resolve()
    main_c = read_text(root / "mouthnose" / "Core" / "Src" / "main.c")
    mic_cfg = read_text(root / "mouthnose" / "Core" / "Inc" / "mic_backend_config.h")
    fft_cfg = read_text(root / "mouthnose" / "Core" / "Inc" / "breath_fft_backend_config.h")
    ai_cfg = read_text(root / "mouthnose" / "Middlewares" / "ST" / "AI" / "Assets" / "breath_ai_config.h")
    model = read_json(root / "mouthnose" / "Middlewares" / "ST" / "AI" / "Assets" / "model_selection.json")

    sample_rate = macro_int(ai_cfg, "BREATH_AI_SAMPLE_RATE") or 0
    hop_size = macro_int(ai_cfg, "BREATH_AI_HOP_SIZE") or 0
    ai_rate = (sample_rate / hop_size) if sample_rate and hop_size else None
    window_ms = macro_int(main_c, "PUMP_ACTION_LED_WINDOW_MS")
    active_ms = macro_int(main_c, "PUMP_ACTION_LED_ACTIVE_MS")
    mouth_pct = macro_int(main_c, "PUMP_ACTION_LED_MOUTH_PERCENT")
    pump_period = macro_int(main_c, "PUMP_PWM_PERIOD")
    pump_clock = macro_int(main_c, "PUMP_PWM_TIMER_CLOCK_HZ")
    pump_freq = (pump_clock / (pump_period + 1)) if pump_clock is not None and pump_period is not None else None

    print("=== STM32 Firmware Status ===")
    print(f"project_root        : {root}")
    print(f"mic_backend         : {active_define(mic_cfg, 'MIC_BACKEND')}")
    print(f"i2s_to_pcm_gain     : {active_define(main_c, 'I2S_TO_PCM_GAIN')}")
    print(f"fft_backend         : {active_define(fft_cfg, 'BREATH_FFT_BACKEND')}")
    print()

    print("=== Model ===")
    print(f"status              : {model.get('status', 'unknown')}")
    print(f"network_name        : {model.get('network_name', 'unknown')}")
    print(f"selected_tflite     : {model.get('selected_tflite', 'unknown')}")
    print(f"feature_count       : {macro_int(ai_cfg, 'BREATH_AI_FEATURE_COUNT')}")
    print(f"labels              : {', '.join(model.get('labels') or [])}")
    print(f"tflite_size_bytes   : {model.get('tflite_size_bytes', macro_int(ai_cfg, 'BREATH_AI_TFLITE_SIZE_BYTES'))}")
    print(f"tflite_frame_acc    : {model.get('tflite_frame_accuracy', macro_float(ai_cfg, 'BREATH_AI_TFLITE_FRAME_ACCURACY'))}")
    print(f"stedgeai_run        : {(model.get('stedgeai') or {}).get('run_id', 'unknown')}")
    print()

    print("=== Feature Extraction ===")
    print(f"sample_rate         : {sample_rate} Hz")
    print(f"frame_size          : {macro_int(ai_cfg, 'BREATH_AI_FRAME_SIZE')} samples")
    print(f"hop_size            : {hop_size} samples")
    print(f"fft_size            : {macro_int(ai_cfg, 'BREATH_AI_FFT_SIZE')}")
    print(f"bandpass            : {macro_float(ai_cfg, 'BREATH_AI_BPF_LOW_HZ')}-{macro_float(ai_cfg, 'BREATH_AI_BPF_HIGH_HZ')} Hz, order={macro_int(ai_cfg, 'BREATH_AI_BPF_ORDER')}")
    print(f"mfcc                : {macro_int(ai_cfg, 'BREATH_AI_NUM_MFCC')} coeffs, {macro_int(ai_cfg, 'BREATH_AI_NUM_MELS')} mel bins")
    print(f"delta_lookahead     : {macro_int(ai_cfg, 'BREATH_AI_DELTA_LOOKAHEAD_FRAMES')} frames / {macro_int(ai_cfg, 'BREATH_AI_DELTA_LOOKAHEAD_MS')} ms")
    print()

    print("=== Runtime AI / LED ===")
    print(f"boot_ai_inference   : {'ON' if 'BreathAI_SetLiveInferenceEnabled(1U)' in main_c else 'OFF/unknown'}")
    print(f"ai_update_rate      : {ai_rate:.2f}/s" if ai_rate else "ai_update_rate      : unknown")
    print(f"stable_history      : {macro_int(main_c, 'AI_STABLE_HISTORY_SIZE')} predictions")
    print(f"stable_min_votes    : {macro_int(main_c, 'AI_STABLE_MIN_VOTES')}")
    print(f"confidence_gate     : {macro_float(main_c, 'AI_CONFIDENCE_GATE')}")
    print(f"class_led_mode_boot : {led_mode_name(c_initializer(main_c, 'led_mode'))}")
    print(f"class_led_pins      : PE0, PE1, PE2, PE3, PE7, pulse={macro_int(main_c, 'CLASS_LED_PULSE_MS')} ms")
    print(f"noise_led_pin       : {active_define(main_c, 'LED_NOISE_PIN')} on GPIOE")
    print()

    print("=== Pump Action Indicator LED ===")
    print(f"pin                 : {active_define(main_c, 'PUMP_ACTION_LED_PIN')} on GPIOE")
    print(f"boot_auto_enabled   : {fmt_bool(c_initializer(main_c, 'pump_action_led_enabled'))}")
    print(f"window              : {window_ms} ms sliding")
    print(f"trigger             : PE0/PE1 mouth LED-selected predictions >= {mouth_pct}%")
    print(f"basis               : follows current LED mode RAW/STABLE/OFF")
    print(f"min_samples         : {macro_int(main_c, 'PUMP_ACTION_LED_MIN_SAMPLES')} predictions")
    print(f"active_time         : {active_ms} ms")
    print(f"effect              : starts PA6 oral/neck pump PWM, pauses AI feature stream and class LEDs while active")
    print()

    print("=== Oral/Neck Pump PWM Actuator ===")
    print(f"pin                 : PA6 / TIM3 CH1")
    print(f"pwm_frequency       : {pump_freq:.1f} Hz" if pump_freq else "pwm_frequency       : unknown")
    print(f"default_duty        : {macro_int(main_c, 'ACTUATOR_DEFAULT_DUTY_PERMILLE')} permille")
    print(f"boot_ai_control     : {fmt_bool(c_initializer(main_c, 'actuator_ai_control_enabled'))}")
    print(f"boot_output         : {fmt_bool(c_initializer(main_c, 'actuator_output_active'))}")
    print(f"run_limit           : {macro_int(main_c, 'ACTUATOR_RUN_MS')} ms")
    print()

    print("=== IMU UART Bridge / Side Airbag ===")
    print("uart                : USART1, PA10 RX from ESP32-S3 TX, PA9 TX optional, 9600 8N1")
    print(f"side_pump_pin       : PA7 / TIM3 CH2")
    print(f"side_valve_pin      : PB1 / GPIO output")
    print(f"side_default_duty   : {macro_int(main_c, 'SIDE_AIR_DEFAULT_DUTY_PERMILLE')} permille")
    print(f"side_run_limit      : {macro_int(main_c, 'SIDE_AIR_RUN_MAX_MS')} ms")
    print("tokens              : L/LEFT,R/RIGHT,N/NORMAL,S/SNIFFING,A/O/ANGLE_OVER")
    print("left/right policy   : one common PA7 pump inflates both side airbags")
    print()

    print("=== Commands ===")
    print("AI ON/OFF, LED RAW/STABLE/OFF, LED TEST 0..5/NOISE/ALL/OFF")
    print("PLED ON/OFF, PUMPLED ON/OFF, PUMP LED ON/OFF")
    print("ACT/PUMP TEST, ON, OFF, DUTY, AI ON/OFF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
