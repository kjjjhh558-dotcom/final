# -*- coding: utf-8 -*-
"""STM32 클래스 LED 표시 정책을 USB CDC 명령으로 변경합니다.

LED RAW/STABLE/OFF 명령을 보내 원시 argmax 표시, 안정화된 투표 결과 표시, LED 비활성화를 선택합니다."""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    serial = None


def parse_args(argv: list[str]) -> argparse.Namespace:
    """LED stable/raw/off 모드와 COM 포트 옵션을 CLI에서 받습니다."""
    parser = argparse.ArgumentParser(description="Send LED RAW/STABLE/OFF command to STM32 USB CDC firmware.")
    parser.add_argument("port", help="serial port, e.g. COM4")
    parser.add_argument("mode", choices=("stable", "raw", "off"), help="class LED display mode")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=1.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """선택한 LED 모드를 STM32 LED RAW/STABLE/OFF 명령으로 전송합니다."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    if args.mode == "raw":
        command = "LED RAW\n"
    elif args.mode == "off":
        command = "LED OFF\n"
    else:
        command = "LED STABLE\n"
    with serial.Serial(args.port, args.baudrate, timeout=args.timeout) as ser:
        time.sleep(0.1)
        ser.write(command.encode("ascii"))
        ser.flush()

    print(f"sent {command.strip()} to {args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
