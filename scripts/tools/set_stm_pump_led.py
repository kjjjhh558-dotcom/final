# -*- coding: utf-8 -*-
"""STM32 펌프 동작 표시 LED 자동 로직을 USB CDC 명령으로 켜거나 끕니다.

PLED ON/OFF 명령을 보내 AI mouth 계열 예측에 따른 펌프 표시 LED 정책을 현장에서 토글합니다."""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    serial = None


def parse_args(argv: list[str]) -> argparse.Namespace:
    """펌프 표시 LED 자동 로직 on/off와 COM 포트 옵션을 읽습니다."""
    parser = argparse.ArgumentParser(description="Send PLED ON/OFF command to STM32 USB CDC firmware.")
    parser.add_argument("port", help="serial port, e.g. COM4")
    parser.add_argument("mode", choices=("on", "off"), help="pump-action indicator LED auto logic")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=1.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """STM32에 PLED ON/OFF 명령을 보내 펌프 표시 LED 정책을 토글합니다."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    command = "PLED ON\n" if args.mode == "on" else "PLED OFF\n"
    with serial.Serial(args.port, args.baudrate, timeout=args.timeout) as ser:
        time.sleep(0.1)
        ser.write(command.encode("ascii"))
        ser.flush()

    print(f"sent {command.strip()} to {args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
