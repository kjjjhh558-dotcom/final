# -*- coding: utf-8 -*-
"""STM32 USB CDC 명령으로 구강/목 펌프 액추에이터를 수동 또는 AI 제어 모드로 전환합니다.

ACT ON/OFF/TEST/DUTY/AI ON/AI OFF 명령을 사람이 쓰기 쉬운 CLI 인자로 감싸 하드웨어 확인과 디버깅을 돕습니다."""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    serial = None


def parse_args(argv: list[str]) -> argparse.Namespace:
    """COM 포트, 액추에이터 모드, PWM duty 옵션을 CLI 인자로 정의합니다."""
    parser = argparse.ArgumentParser(description="Send pump/actuator command to STM32 USB CDC firmware.")
    parser.add_argument("port", help="serial port, e.g. COM4")
    parser.add_argument(
        "mode",
        choices=("off", "test", "on", "ai-on", "ai-off", "duty"),
        help="actuator command",
    )
    parser.add_argument(
        "--duty",
        type=int,
        default=None,
        help="PWM duty. 0-100 means percent, 101-1000 means permille.",
    )
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=1.0)
    return parser.parse_args(argv)


def build_command(mode: str, duty: int | None) -> str:
    """off/test/on/ai/duty 모드를 STM32 ACT 명령 문자열로 변환하고 필수 duty를 검증합니다."""
    if mode == "off":
        return "ACT OFF\n"
    if mode == "ai-on":
        return "ACT AI ON\n"
    if mode == "ai-off":
        return "ACT AI OFF\n"
    if mode == "test":
        return f"ACT TEST {duty}\n" if duty is not None else "ACT TEST\n"
    if mode == "on":
        return f"ACT ON {duty}\n" if duty is not None else "ACT ON\n"
    if mode == "duty":
        if duty is None:
            raise ValueError("--duty is required when mode is duty")
        return f"ACT DUTY {duty}\n"
    raise ValueError(f"unsupported mode: {mode}")


def main(argv: list[str] | None = None) -> int:
    """명령 문자열을 만들고 STM32 USB CDC 포트로 전송합니다."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    try:
        command = build_command(args.mode, args.duty)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    with serial.Serial(args.port, args.baudrate, timeout=args.timeout) as ser:
        time.sleep(0.1)
        ser.write(command.encode("ascii"))
        ser.flush()

    print(f"sent {command.strip()} to {args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
