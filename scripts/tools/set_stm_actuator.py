# -*- coding: utf-8 -*-
"""Send actuator control commands to STM32 USB CDC firmware."""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    serial = None


def parse_args(argv: list[str]) -> argparse.Namespace:
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
