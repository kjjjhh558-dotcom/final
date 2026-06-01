# -*- coding: utf-8 -*-
"""Exercise the oral airbag pump and exhaust solenoid valve over STM32 USB CDC."""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    serial = None


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Test the oral breathing airbag solenoid valve. "
            "Use click mode for valve-only checking, and inflate-vent mode "
            "to inflate with the pump and then vent with the OUT command."
        )
    )
    parser.add_argument("port", help="serial port, e.g. COM4")
    parser.add_argument(
        "mode",
        choices=("click", "inflate-vent", "vent"),
        help="test mode",
    )
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--cycles", type=positive_int, default=5, help="VALVE ON/OFF cycles for click mode.")
    parser.add_argument("--on-ms", type=positive_int, default=500, help="VALVE ON time per click cycle.")
    parser.add_argument("--off-ms", type=positive_int, default=500, help="VALVE OFF time per click cycle.")
    parser.add_argument("--duty", type=int, default=60, help="Pump PWM duty. 0-100 means percent.")
    parser.add_argument("--inflate-sec", type=positive_float, default=2.0, help="Pump run time for inflate-vent mode.")
    parser.add_argument("--vent-sec", type=positive_float, default=5.0, help="Observation time after OUT opens the exhaust valve.")
    parser.add_argument("--yes", action="store_true", help="Run without the safety confirmation prompt.")
    return parser.parse_args(argv)


def send_command(ser: "serial.Serial", command: str) -> None:
    line = command.strip()
    print(f"> {line}")
    ser.write((line + "\n").encode("ascii"))
    ser.flush()
    time.sleep(0.05)


def wait_seconds(seconds: float, label: str) -> None:
    if seconds <= 0:
        return
    print(f"... {label}: {seconds:.1f}s")
    time.sleep(seconds)


def confirm(args: argparse.Namespace) -> None:
    if args.yes:
        return

    print("[SAFETY] Check these before continuing:")
    print("  - 12V adapter minus, STM32 GND, and HW-532 GND are common.")
    print("  - Pump and valve each have their own flyback diode.")
    print("  - The airbag has a safe pressure path and can be disconnected quickly.")
    print("  - The pump OUT is connected to the airbag fill port.")
    print("  - The valve is connected to the airbag exhaust port, and its outlet is not blocked.")
    input("Press Enter to start the test, or Ctrl+C to cancel...")


def run_click(ser: "serial.Serial", args: argparse.Namespace) -> None:
    cycles = max(1, args.cycles)
    for idx in range(cycles):
        print(f"[cycle {idx + 1}/{cycles}] valve ON")
        send_command(ser, "VALVE ON")
        wait_seconds(args.on_ms / 1000.0, "listen/feel valve ON")
        print(f"[cycle {idx + 1}/{cycles}] valve OFF")
        send_command(ser, "VALVE OFF")
        wait_seconds(args.off_ms / 1000.0, "listen/feel valve OFF")


def run_inflate_vent(ser: "serial.Serial", args: argparse.Namespace) -> None:
    duty = max(0, min(100, args.duty))
    print("[step 1] Close exhaust valve")
    send_command(ser, "VALVE OFF")
    wait_seconds(0.2, "exhaust closed")

    print("[step 2] Start pump")
    send_command(ser, f"ACT ON {duty}")
    wait_seconds(args.inflate_sec, "inflate airbag")

    print("[step 3] Send OUT: stop pump and open exhaust valve")
    send_command(ser, "OUT")
    wait_seconds(args.vent_sec, "airbag deflate observation")


def run_vent(ser: "serial.Serial", args: argparse.Namespace) -> None:
    print("[vent] Stop pump and open exhaust valve")
    send_command(ser, "OUT")
    wait_seconds(args.vent_sec, "airbag deflate observation")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    confirm(args)

    with serial.Serial(args.port, args.baudrate, timeout=args.timeout) as ser:
        time.sleep(0.1)
        if args.mode == "click":
            run_click(ser, args)
        elif args.mode == "inflate-vent":
            run_inflate_vent(ser, args)
        elif args.mode == "vent":
            run_vent(ser, args)
        else:
            raise ValueError(f"unsupported mode: {args.mode}")

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
