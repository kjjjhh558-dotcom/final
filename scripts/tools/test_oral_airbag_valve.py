# -*- coding: utf-8 -*-
"""구강 에어백 펌프와 배기 솔레노이드 밸브를 안전 확인 후 단계적으로 시험합니다.

click은 밸브 단독 클릭 테스트, inflate-vent는 펌프로 팽창 후 OUT으로 배기, vent는 즉시 배기 동작을 확인합니다."""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    serial = None


def positive_float(value: str) -> float:
    """시간 인자가 음수가 아닌 float인지 검증합니다."""
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def positive_int(value: str) -> int:
    """반복 횟수나 ms 인자가 음수가 아닌 int인지 검증합니다."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def parse_args(argv: list[str]) -> argparse.Namespace:
    """구강 에어백 테스트 모드와 안전 관련 실행 옵션을 정의합니다."""
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
    """STM32 USB CDC로 한 줄 명령을 보내고 콘솔에 같은 내용을 표시합니다."""
    line = command.strip()
    print(f"> {line}")
    ser.write((line + "\n").encode("ascii"))
    ser.flush()
    time.sleep(0.05)


def wait_seconds(seconds: float, label: str) -> None:
    """테스트 단계 사이 관찰 시간을 사람이 알 수 있게 출력하며 대기합니다."""
    if seconds <= 0:
        return
    print(f"... {label}: {seconds:.1f}s")
    time.sleep(seconds)


def confirm(args: argparse.Namespace) -> None:
    """펌프/밸브 전원과 배기 안전 경로를 확인하도록 실행 전 안전 프롬프트를 표시합니다."""
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
    """밸브 ON/OFF를 반복해 솔레노이드 클릭과 배선 상태를 확인합니다."""
    cycles = max(1, args.cycles)
    for idx in range(cycles):
        print(f"[cycle {idx + 1}/{cycles}] valve ON")
        send_command(ser, "VALVE ON")
        wait_seconds(args.on_ms / 1000.0, "listen/feel valve ON")
        print(f"[cycle {idx + 1}/{cycles}] valve OFF")
        send_command(ser, "VALVE OFF")
        wait_seconds(args.off_ms / 1000.0, "listen/feel valve OFF")


def run_inflate_vent(ser: "serial.Serial", args: argparse.Namespace) -> None:
    """배기 밸브를 닫고 펌프로 팽창시킨 뒤 OUT 명령으로 배기 동작을 확인합니다."""
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
    """펌프를 멈추고 배기 밸브를 열어 에어백이 빠지는지 확인합니다."""
    print("[vent] Stop pump and open exhaust valve")
    send_command(ser, "OUT")
    wait_seconds(args.vent_sec, "airbag deflate observation")


def main(argv: list[str] | None = None) -> int:
    """안전 확인 후 선택한 구강 에어백 테스트 시나리오를 실행합니다."""
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
