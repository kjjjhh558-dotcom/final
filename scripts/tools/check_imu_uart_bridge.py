# -*- coding: utf-8 -*-
"""Monitor STM32 USART1 IMU bridge telemetry over the USB CDC COM port."""

from __future__ import annotations

import argparse
import struct
import sys
import time

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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enable STM32 IMU bridge telemetry and print USART1 RX/state counters. "
            "Use this while ESP32-S3 TX is wired to STM32 PA10/RX1."
        )
    )
    parser.add_argument("port", help="STM32 USB CDC COM port, e.g. COM4")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=30.0, help="monitor duration in seconds")
    parser.add_argument("--timeout", type=float, default=0.05)
    parser.add_argument("--no-reset", action="store_true", help="do not reset IMU bridge counters before monitoring")
    parser.add_argument("--keep-on", action="store_true", help="leave STM32 IMU telemetry enabled on exit")
    return parser.parse_args(argv)


def state_name(value: int) -> str:
    return STATE_NAMES.get(value, f"STATE_{value}")


def byte_repr(value: int) -> str:
    if value == 0:
        return "none"
    if 32 <= value <= 126:
        return f"'{chr(value)}'/0x{value:02X}"
    return f"0x{value:02X}"


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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    deadline = time.monotonic() + max(0.1, args.duration)
    buffer = bytearray()
    packet_count = 0

    with serial.Serial(args.port, args.baudrate, timeout=args.timeout) as ser:
        time.sleep(0.1)
        ser.reset_input_buffer()
        if not args.no_reset:
            ser.write(b"IMU RESET\n")
            ser.flush()
            time.sleep(0.05)
        ser.write(b"IMU ON\n")
        ser.flush()

        print("STM32 IMU bridge telemetry enabled.")
        print("Wire check: ESP32-S3 TX -> STM32 PA10/RX1, ESP32-S3 GND -> STM32 GND")
        print("Expected tokens from ESP32-S3: L/R/N/S/F/O/A or LEFT/RIGHT/NORMAL/SNIFFING/FRONT_LOW/ANGLE_OVER")

        try:
            while time.monotonic() < deadline:
                chunk = ser.read(4096)
                if chunk:
                    buffer.extend(chunk)

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

                    packet = bytes(buffer[:IMU_PACKET_SIZE])
                    del buffer[:IMU_PACKET_SIZE]
                    data = unpack_packet(packet)
                    if data["magic"] != IMU_MAGIC:
                        continue

                    packet_count += 1
                    print(
                        "seq={seq:04d} t={tick_ms:8d}ms "
                        "rx={rx_count:5d} valid={valid_count:4d} invalid={invalid_count:3d} "
                        "state={state:<10s} last={last_state:<10s} pending={pending_state:<10s} "
                        "byte={last_byte:<8s} side_pump={side_pump} side_valve={side_valve} "
                        "oral_pump={oral_pump} side_start/stop/safety={start}/{stop}/{safety}".format(
                            seq=data["seq"],
                            tick_ms=data["tick_ms"],
                            rx_count=data["rx_count"],
                            valid_count=data["valid_count"],
                            invalid_count=data["invalid_count"],
                            state=state_name(data["state"]),
                            last_state=state_name(data["last_state"]),
                            pending_state=state_name(data["pending_state"]),
                            last_byte=byte_repr(data["last_rx_byte"]),
                            side_pump=data["side_pump_active"],
                            side_valve=data["side_valve_active"],
                            oral_pump=data["oral_pump_active"],
                            start=data["side_start_count"],
                            stop=data["side_stop_count"],
                            safety=data["side_safety_stop_count"],
                        )
                    )

                time.sleep(0.01)
        finally:
            if not args.keep_on:
                ser.write(b"IMU OFF\n")
                ser.flush()

    if packet_count == 0:
        print("[WARN] No IMU telemetry packets received. Check COM port, flashed firmware, and USB CDC availability.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
