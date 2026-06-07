# -*- coding: utf-8 -*-
"""nRF52840 IMU BLE 알림이 ESP32-S3를 거쳐 STM32 UART까지 도달하는지 끝단 간 검증합니다.

ESP32-S3 USB 로그와 STM32 IMU 텔레메트리를 동시에 읽어 BLE notify, UART TX, STM32 RX/valid 카운터가 순서대로 증가하는지 판정합니다."""

from __future__ import annotations

import argparse
import re
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

NOTIFY_RE = re.compile(r"(?:BRIDGE_NOTIFY|BLE notify) state=(?P<state>\S).*?notify=(?P<notify>\d+).*?(?:uart_tx=|STM32 UART tx=)(?P<uart_tx>\d+)")
STATUS_RE = re.compile(r"(?:BRIDGE_STATUS|status) connected=(?P<connected>\S+) last=(?P<state>\S+) notify=(?P<notify>\d+) uart_tx=(?P<uart_tx>\d+)")
TEAM_DATA_RE = re.compile(r"Data Received:\s*(?P<state>[LRNSFOA])")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """STM32와 ESP32-S3 COM 포트, baudrate, 관찰 시간을 CLI로 받습니다."""
    parser = argparse.ArgumentParser(
        description=(
            "Read ESP32-S3 USB logs and STM32 IMU telemetry together to verify "
            "that nRF52840 BLE notify data reaches STM32 USART1."
        )
    )
    parser.add_argument("--stm-port", default="COM4", help="STM32 USB CDC port")
    parser.add_argument("--esp-port", default="COM7", help="ESP32-S3 USB serial port")
    parser.add_argument("--stm-baudrate", type=int, default=115200)
    parser.add_argument("--esp-baudrate", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=0.03)
    parser.add_argument("--keep-stm-imu-on", action="store_true")
    return parser.parse_args(argv)


def state_name(value: int) -> str:
    """STM32 자세 상태 숫자를 사람이 읽는 이름으로 변환합니다."""
    return STATE_NAMES.get(value, f"STATE_{value}")


def byte_repr(value: int) -> str:
    """STM32 마지막 UART 바이트를 디버깅하기 좋은 문자열로 바꿉니다."""
    if value == 0:
        return "none"
    if 32 <= value <= 126:
        return f"'{chr(value)}'/0x{value:02X}"
    return f"0x{value:02X}"


def unpack_stm_packet(packet: bytes) -> dict[str, int]:
    """STM32 IMU 텔레메트리 binary packet을 dict 필드로 해석합니다."""
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


def process_stm_buffer(buffer: bytearray) -> list[dict[str, int]]:
    """시리얼 버퍼에서 magic을 찾아 완성된 STM32 텔레메트리 패킷만 추출합니다."""
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
        packet = unpack_stm_packet(raw)
        if packet["magic"] == IMU_MAGIC:
            packets.append(packet)
    return packets


def read_esp_lines(esp: "serial.Serial", line_buffer: bytearray) -> list[str]:
    """ESP32-S3 USB 로그 버퍼에서 줄 단위 텍스트를 안전하게 잘라냅니다."""
    lines: list[str] = []
    data = esp.read(4096)
    if data:
        line_buffer.extend(data)
    while True:
        newline_positions = [pos for pos in (line_buffer.find(b"\n"), line_buffer.find(b"\r")) if pos >= 0]
        if not newline_positions:
            break
        pos = min(newline_positions)
        raw = bytes(line_buffer[:pos])
        del line_buffer[: pos + 1]
        text = raw.decode("utf-8", errors="replace").strip()
        if text:
            lines.append(text)
    return lines


def main(argv: list[str] | None = None) -> int:
    """ESP notify/UART TX와 STM32 RX/valid 증가를 함께 관찰해 end-to-end 판정을 출력합니다."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if serial is None:
        print("[ERROR] pyserial is required. Install it with: python -m pip install pyserial", file=sys.stderr)
        return 1

    deadline = time.monotonic() + max(0.1, args.duration)
    stm_buffer = bytearray()
    esp_line_buffer = bytearray()
    latest_stm: dict[str, int] | None = None
    esp_connected = "unknown"
    esp_last_state = "?"
    esp_notify = 0
    esp_uart_tx = 0
    esp_lines_seen = 0
    stm_packets = 0
    last_stm_rx = 0
    last_stm_valid = 0

    with serial.Serial(args.stm_port, args.stm_baudrate, timeout=args.timeout) as stm, \
            serial.Serial(args.esp_port, args.esp_baudrate, timeout=args.timeout) as esp:
        time.sleep(0.2)
        stm.reset_input_buffer()
        esp.reset_input_buffer()
        stm.write(b"IMU RESET\n")
        stm.write(b"IMU ON\n")
        stm.flush()

        print("End-to-end bridge monitor started.")
        print(f"STM32={args.stm_port}, ESP32-S3={args.esp_port}")
        print("Expected: ESP notify/uart_tx increase first, then STM rx/valid/state follows.")

        try:
            while time.monotonic() < deadline:
                stm_chunk = stm.read(4096)
                if stm_chunk:
                    stm_buffer.extend(stm_chunk)
                    for packet in process_stm_buffer(stm_buffer):
                        latest_stm = packet
                        stm_packets += 1
                        last_stm_rx = packet["rx_count"]
                        last_stm_valid = packet["valid_count"]

                for line in read_esp_lines(esp, esp_line_buffer):
                    esp_lines_seen += 1
                    notify_match = NOTIFY_RE.search(line)
                    status_match = STATUS_RE.search(line)
                    if notify_match:
                        esp_last_state = notify_match.group("state")
                        esp_notify = int(notify_match.group("notify"))
                        esp_uart_tx = int(notify_match.group("uart_tx"))
                    elif status_match:
                        esp_connected = status_match.group("connected")
                        esp_last_state = status_match.group("state")
                        esp_notify = int(status_match.group("notify"))
                        esp_uart_tx = int(status_match.group("uart_tx"))
                    elif TEAM_DATA_RE.search(line):
                        team_match = TEAM_DATA_RE.search(line)
                        esp_connected = "yes"
                        esp_last_state = team_match.group("state")
                        esp_notify += 1
                        esp_uart_tx += 1
                    elif "BRIDGE_CONNECTED" in line:
                        esp_connected = "yes"
                    elif "BRIDGE_DISCONNECTED" in line:
                        esp_connected = "no"
                    print(f"[esp] {line}")

                if latest_stm is not None:
                    print(
                        "[stm] seq={seq:04d} rx={rx:5d} valid={valid:4d} invalid={invalid:3d} "
                        "state={state:<10s} byte={byte:<8s} side_pump={side_pump} side_valve={side_valve} "
                        "| [esp-summary] connected={esp_connected} last={esp_state} notify={esp_notify} uart_tx={esp_uart}".format(
                            seq=latest_stm["seq"],
                            rx=latest_stm["rx_count"],
                            valid=latest_stm["valid_count"],
                            invalid=latest_stm["invalid_count"],
                            state=state_name(latest_stm["state"]),
                            byte=byte_repr(latest_stm["last_rx_byte"]),
                            side_pump=latest_stm["side_pump_active"],
                            side_valve=latest_stm["side_valve_active"],
                            esp_connected=esp_connected,
                            esp_state=esp_last_state,
                            esp_notify=esp_notify,
                            esp_uart=esp_uart_tx,
                        )
                    )
                    latest_stm = None

                time.sleep(0.05)
        finally:
            if not args.keep_stm_imu_on:
                stm.write(b"IMU OFF\n")
                stm.flush()

    print()
    print("=== Verdict ===")
    if esp_notify > 0 and esp_uart_tx > 0 and stm_packets > 0:
        print(f"ESP BLE notify seen: notify={esp_notify}, uart_tx={esp_uart_tx}")
    elif esp_lines_seen == 0:
        print("No ESP32-S3 USB log lines were read. Close Arduino Serial Monitor or check esp-port.")
    elif esp_notify == 0:
        print("ESP32-S3 logs were read, but BLE notify did not increase. Check nRF power, BLE pairing/range, and service UUID.")

    if esp_notify > 0 and esp_uart_tx > 0 and last_stm_rx > 0 and last_stm_valid > 0:
        print(f"PASS: nRF BLE notify reached STM32. stm_rx={last_stm_rx}, stm_valid={last_stm_valid}")
        return 0

    if esp_notify > 0 and esp_uart_tx > 0 and last_stm_rx == 0:
        print("ESP received nRF BLE and transmitted UART, but STM32 rx stayed 0. Check D6/TX -> PA10/RX1 and common GND.")
    elif esp_notify > 0 and esp_uart_tx > 0 and last_stm_valid == 0:
        print("STM32 received UART bytes, but valid stayed 0. Check token characters and baudrate.")

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
