# -*- coding: utf-8 -*-
# 파일 설명: USB CDC 명령으로 STM32 보드의 실시간 AI 추론 출력을 켜거나 끕니다.
"""STM32 보드의 실시간 AI 추론 패킷 출력을 USB CDC 명령으로 켜거나 끕니다.

AI ON/OFF 명령을 보내므로 실시간 모니터링 중 보드 추론 출력만 빠르게 제어할 때 사용합니다."""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    serial = None


# 함수 설명: 명령행 옵션을 정의하고 사용자가 입력한 인자를 파싱합니다.
def parse_args(argv: list[str]) -> argparse.Namespace:
    """AI ON/OFF 제어에 필요한 COM 포트와 시리얼 옵션을 읽습니다."""
    parser = argparse.ArgumentParser(description="Send AI ON/OFF command to STM32 USB CDC firmware.")
    parser.add_argument("port", help="serial port, e.g. COM4")
    parser.add_argument("mode", choices=("on", "off"), help="live AI inference mode")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=1.0)
    return parser.parse_args(argv)


# 함수 설명: 스크립트 진입점으로 인자를 읽고 전체 실행 흐름을 호출합니다.
def main(argv: list[str] | None = None) -> int:
    """STM32에 AI ON 또는 AI OFF 명령을 보내 실시간 추론 패킷 출력을 토글합니다."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    command = "AI ON\n" if args.mode == "on" else "AI OFF\n"
    with serial.Serial(args.port, args.baudrate, timeout=args.timeout) as ser:
        time.sleep(0.1)
        ser.write(command.encode("ascii"))
        ser.flush()

    print(f"sent {command.strip()} to {args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
