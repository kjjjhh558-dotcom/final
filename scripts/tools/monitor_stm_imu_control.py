# -*- coding: utf-8 -*-
"""Show the final IMU posture state and actuator outputs as seen by STM32 only."""

from __future__ import annotations

import argparse
import struct
import sys
import time
from datetime import datetime

try:
    import serial
except ImportError:
    serial = None


IMU_MAGIC = 0x1A71B2E1
IMU_MAGIC_BYTES = struct.pack("<I", IMU_MAGIC)
IMU_PACKET_FMT = "<16I"
IMU_PACKET_SIZE = struct.calcsize(IMU_PACKET_FMT)

STATE_NAMES = {
    0: "UNKNOWN",
    1: "NORMAL",
    2: "LEFT",
    3: "RIGHT",
    4: "SNIFFING",
    5: "ANGLE_OVER",
    6: "FRONT_LOW",
}

STATE_LABELS_KO = {
    "UNKNOWN": "미수신",
    "NORMAL": "보통",
    "LEFT": "좌측 기울어짐",
    "RIGHT": "우측 기울어짐",
    "SNIFFING": "스니핑 각도",
    "ANGLE_OVER": "각도 과다",
    "FRONT_LOW": "전방 낮음",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Monitor only STM32-side IMU bridge telemetry. "
            "This does not open the ESP32-S3 COM port; it shows what STM32 finally received "
            "and how STM32 is driving the pump/valve outputs."
        )
    )
    parser.add_argument("port", help="STM32 USB CDC COM port, e.g. COM4")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=0.05)
    parser.add_argument("--show-all", action="store_true", help="print every telemetry packet instead of only changes")
    parser.add_argument("--heartbeat", type=float, default=2.0, help="seconds between unchanged status lines")
    parser.add_argument("--no-reset", action="store_true", help="do not reset STM32 IMU counters before monitoring")
    parser.add_argument("--keep-on", action="store_true", help="leave STM32 IMU telemetry enabled on exit")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    return parser.parse_args(argv)


def state_name(value: int) -> str:
    return STATE_NAMES.get(value, f"STATE_{value}")


def byte_repr(value: int) -> str:
    if value == 0:
        return "none"
    if 32 <= value <= 126:
        return f"'{chr(value)}'/0x{value:02X}"
    return f"0x{value:02X}"


def onoff(value: int) -> str:
    return "ON" if value else "OFF"


def valve_text(value: int) -> str:
    return "OPEN" if value else "CLOSED"


def color(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def unpack_packet(packet: bytes) -> dict[str, int]:
    fields = struct.unpack(IMU_PACKET_FMT, packet)
    keys = (
        "magic",
        "seq",
        "tick_ms",
        "rx_count",
        "valid_count",
        "invalid_count",
        "state",
        "last_state",
        "pending_state",
        "last_rx_byte",
        "side_pump_active",
        "side_valve_active",
        "oral_pump_active",
        "side_start_count",
        "side_stop_count",
        "side_safety_stop_count",
    )
    return dict(zip(keys, fields, strict=True))


def process_buffer(buffer: bytearray) -> list[dict[str, int]]:
    packets: list[dict[str, int]] = []
    while True:
        idx = buffer.find(IMU_MAGIC_BYTES)
        if idx < 0:
            if len(buffer) > 3:
                del buffer[:-3]
            break
        if idx > 0:
            del buffer[:idx]
        if len(buffer) < IMU_PACKET_SIZE:
            break

        raw = bytes(buffer[:IMU_PACKET_SIZE])
        del buffer[:IMU_PACKET_SIZE]
        data = unpack_packet(raw)
        if data["magic"] == IMU_MAGIC:
            packets.append(data)
    return packets


def expected_control(state: str) -> tuple[int | None, int | None, int | None, str]:
    if state in ("LEFT", "RIGHT"):
        return 1, 0, None, "좌/우 보정: PA7 side pump ON, PB1 side valve CLOSED"
    if state in ("NORMAL", "FRONT_LOW"):
        return 0, 1, None, "좌/우 보정 해제: PA7 side pump OFF, PB1 side valve OPEN"
    if state in ("SNIFFING", "ANGLE_OVER"):
        return 0, 1, 0, "안전/목표각: PA7 OFF, PB1 OPEN, PA6 oral pump OFF"
    return None, None, None, "아직 유효한 자세 토큰 없음"


def control_check(data: dict[str, int], state: str) -> tuple[str, str]:
    exp_side_pump, exp_side_valve, exp_oral_pump, reason = expected_control(state)
    checks: list[bool] = []
    if exp_side_pump is not None:
        checks.append(data["side_pump_active"] == exp_side_pump)
    if exp_side_valve is not None:
        checks.append(data["side_valve_active"] == exp_side_valve)
    if exp_oral_pump is not None:
        checks.append(data["oral_pump_active"] == exp_oral_pump)
    if not checks:
        return "WAIT", reason
    return ("OK" if all(checks) else "CHECK"), reason


def line_key(data: dict[str, int]) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        data["state"],
        data["last_rx_byte"],
        data["side_pump_active"],
        data["side_valve_active"],
        data["oral_pump_active"],
        data["invalid_count"],
        data["side_start_count"],
        data["side_stop_count"],
        data["side_safety_stop_count"],
    )


def format_line(data: dict[str, int], use_color: bool) -> str:
    state = state_name(data["state"])
    label = STATE_LABELS_KO.get(state, state)
    check, reason = control_check(data, state)

    state_display = f"{state}/{label}"
    if state in ("LEFT", "RIGHT"):
        state_display = color(state_display, "33", use_color)
    elif state == "SNIFFING":
        state_display = color(state_display, "36", use_color)
    elif state == "ANGLE_OVER":
        state_display = color(state_display, "31", use_color)
    elif state == "NORMAL":
        state_display = color(state_display, "32", use_color)

    check_display = check
    if check == "OK":
        check_display = color("OK", "32", use_color)
    elif check == "CHECK":
        check_display = color("CHECK", "31", use_color)

    return (
        f"{datetime.now().strftime('%H:%M:%S')} "
        f"seq={data['seq']:04d} stm_rx={data['rx_count']:4d} valid={data['valid_count']:4d} "
        f"invalid={data['invalid_count']:3d} byte={byte_repr(data['last_rx_byte']):<8s} "
        f"state={state_display:<22s} "
        f"PA7_side_pump={onoff(data['side_pump_active']):<3s} "
        f"PB1_side_valve={valve_text(data['side_valve_active']):<6s} "
        f"PA6_oral_pump={onoff(data['oral_pump_active']):<3s} "
        f"control={check_display:<5s} "
        f"side_counts={data['side_start_count']}/{data['side_stop_count']}/{data['side_safety_stop_count']} "
        f"| {reason}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    deadline = time.monotonic() + max(0.1, args.duration)
    buffer = bytearray()
    packets = 0
    last_key: tuple[int, int, int, int, int, int, int, int, int] | None = None
    last_print_at = 0.0
    use_color = not args.no_color

    with serial.Serial(args.port, args.baudrate, timeout=args.timeout) as ser:
        time.sleep(0.1)
        ser.reset_input_buffer()
        if not args.no_reset:
            ser.write(b"IMU RESET\n")
            ser.flush()
            time.sleep(0.05)
        ser.write(b"IMU ON\n")
        ser.flush()

        print("STM32-only IMU/control monitor enabled.")
        print("This reads only STM32 USB CDC telemetry. ESP32-S3 COM/log is not used.")
        print("Wire: ESP32-S3 TX -> STM32 PA10/RX1, common GND. Expected tokens: L/R/N/S/F/O/A.")
        print("Columns: STM received byte/state, then STM output states for PA7/PB1/PA6.")

        try:
            while time.monotonic() < deadline:
                chunk = ser.read(4096)
                if chunk:
                    buffer.extend(chunk)

                for data in process_buffer(buffer):
                    packets += 1
                    now = time.monotonic()
                    current_key = line_key(data)
                    changed = current_key != last_key
                    heartbeat_due = (now - last_print_at) >= max(0.1, args.heartbeat)
                    if args.show_all or changed or heartbeat_due:
                        print(format_line(data, use_color))
                        last_key = current_key
                        last_print_at = now

                time.sleep(0.01)
        finally:
            if not args.keep_on:
                ser.write(b"IMU OFF\n")
                ser.flush()

    if packets == 0:
        print("[WARN] No STM32 IMU telemetry packets received. Check COM port, flashed firmware, and USB CDC.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
