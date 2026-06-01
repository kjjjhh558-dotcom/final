# -*- coding: utf-8 -*-
"""Force STM32 class/pump LEDs on or off for GPIO hardware checks."""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    serial = None


LED_COMMANDS = {
    "mouth-exhale": "LED TEST 0\n",
    "mouth-inhale": "LED TEST 1\n",
    "nasal-exhale": "LED TEST 2\n",
    "nasal-inhale": "LED TEST 3\n",
    "noise": "LED TEST NOISE\n",
    "pe7": "LED TEST PE7\n",
    "pump-led": "LED TEST PUMP\n",
    "pe5": "LED TEST PE5\n",
    "all": "LED TEST ALL\n",
    "off": "LED TEST OFF\n",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Force STM32 LED GPIOs for multimeter/LED wiring checks."
    )
    parser.add_argument("port", help="serial port, e.g. COM4")
    parser.add_argument(
        "target",
        choices=tuple(LED_COMMANDS),
        help="LED/GPIO target to force. 'noise' is PE7, 'pump-led' is PE5.",
    )
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=1.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    command = LED_COMMANDS[args.target]
    with serial.Serial(args.port, args.baudrate, timeout=args.timeout) as ser:
        time.sleep(0.1)
        ser.write(command.encode("ascii"))
        ser.flush()

    print(f"sent {command.strip()} to {args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
