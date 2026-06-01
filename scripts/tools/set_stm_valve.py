# -*- coding: utf-8 -*-
"""Send oral air valve control commands to STM32 USB CDC firmware."""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    serial = None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send oral air valve command to STM32 USB CDC firmware.")
    parser.add_argument("port", help="serial port, e.g. COM4")
    parser.add_argument("mode", choices=("off", "test", "on", "out"), help="valve command")
    parser.add_argument("--duration-ms", type=int, default=None, help="VALVE TEST pulse duration in ms.")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=1.0)
    return parser.parse_args(argv)


def build_command(mode: str, duration_ms: int | None) -> str:
    if mode == "off":
        return "VALVE OFF\n"
    if mode == "out":
        return "OUT\n"
    if mode == "on":
        return "VALVE ON\n"
    if mode == "test":
        if duration_ms is not None:
            return f"VALVE TEST {max(1, duration_ms)}\n"
        return "VALVE TEST\n"
    raise ValueError(f"unsupported mode: {mode}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    command = build_command(args.mode, args.duration_ms)

    with serial.Serial(args.port, args.baudrate, timeout=args.timeout) as ser:
        time.sleep(0.1)
        ser.write(command.encode("ascii"))
        ser.flush()

    print(f"sent {command.strip()} to {args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
