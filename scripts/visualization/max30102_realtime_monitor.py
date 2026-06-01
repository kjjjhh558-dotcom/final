# -*- coding: utf-8 -*-
"""Realtime MAX30102 telemetry plotter for the STM32 USB CDC stream.

The firmware keeps sending audio and AI packets on the same COM port.  This
monitor enables MAX30102 telemetry with ``MAX ON`` and then skips unrelated
audio/AI packets while plotting only MAX30102 RED/IR/SpO2 values.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import csv
from pathlib import Path
import struct
import sys
import time

try:
    import serial
except ImportError:  # pragma: no cover - handled at runtime
    serial = None

AUDIO_MAGIC = 0xAABBCCDD
AI_MAGIC = 0xA15A1EAF
MAX30102_MAGIC = 0xA3025A02

MAGIC_BYTES = {
    AUDIO_MAGIC.to_bytes(4, "little"): "audio",
    AI_MAGIC.to_bytes(4, "little"): "ai",
    MAX30102_MAGIC.to_bytes(4, "little"): "max",
}

AUDIO_HEADER_REST = struct.Struct("<IHH")
AI_PACKET_REST = struct.Struct("<IIHHII5f")
MAX30102_PACKET = struct.Struct("<IIIIiiiifII")

DEFAULT_BAUDRATE = 115200
DEFAULT_READ_CHUNK = 4096


@dataclass(frozen=True)
class Max30102Packet:
    seq: int
    tick_ms: int
    sample_count: int
    red: int
    ir: int
    heart_rate_bpm: int
    spo2_percent: int
    ratio: float
    flags: int
    i2c_error_count: int

    @property
    def initialized(self) -> bool:
        return bool(self.flags & (1 << 0))

    @property
    def present(self) -> bool:
        return bool(self.flags & (1 << 1))

    @property
    def finger_detected(self) -> bool:
        return bool(self.flags & (1 << 2))

    @property
    def spo2_ok(self) -> bool:
        return bool(self.flags & (1 << 3))

    @property
    def status(self) -> int:
        return (self.flags >> 8) & 0xFF


class PacketParser:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.skipped_audio_packets = 0
        self.skipped_ai_packets = 0
        self.resync_bytes = 0

    def feed(self, data: bytes) -> list[Max30102Packet]:
        self.buffer.extend(data)
        packets: list[Max30102Packet] = []

        while True:
            parsed = self._parse_one()
            if parsed is None:
                break
            if isinstance(parsed, Max30102Packet):
                packets.append(parsed)

        return packets

    def _find_next_magic(self) -> tuple[int, str] | None:
        best_index: int | None = None
        best_kind: str | None = None
        for magic, kind in MAGIC_BYTES.items():
            idx = self.buffer.find(magic)
            if idx >= 0 and (best_index is None or idx < best_index):
                best_index = idx
                best_kind = kind

        if best_index is None or best_kind is None:
            keep = min(len(self.buffer), 3)
            if len(self.buffer) > keep:
                self.resync_bytes += len(self.buffer) - keep
                del self.buffer[:-keep]
            return None

        if best_index > 0:
            self.resync_bytes += best_index
            del self.buffer[:best_index]

        return 0, best_kind

    def _parse_one(self) -> Max30102Packet | bool | None:
        found = self._find_next_magic()
        if found is None:
            return None
        _, kind = found

        if kind == "audio":
            header_len = 4 + AUDIO_HEADER_REST.size
            if len(self.buffer) < header_len:
                return None
            seq, samples, reserved = AUDIO_HEADER_REST.unpack_from(self.buffer, 4)
            _ = seq, reserved
            if samples <= 0 or samples > 4096:
                del self.buffer[:1]
                return True
            packet_len = header_len + samples * 2
            if len(self.buffer) < packet_len:
                return None
            del self.buffer[:packet_len]
            self.skipped_audio_packets += 1
            return True

        if kind == "ai":
            packet_len = 4 + AI_PACKET_REST.size
            if len(self.buffer) < packet_len:
                return None
            del self.buffer[:packet_len]
            self.skipped_ai_packets += 1
            return True

        packet_len = MAX30102_PACKET.size
        if len(self.buffer) < packet_len:
            return None

        (
            magic,
            seq,
            tick_ms,
            sample_count,
            red,
            ir,
            heart_rate_bpm,
            spo2_percent,
            ratio,
            flags,
            i2c_error_count,
        ) = MAX30102_PACKET.unpack_from(self.buffer, 0)
        if magic != MAX30102_MAGIC:
            del self.buffer[:1]
            return True

        del self.buffer[:packet_len]
        return Max30102Packet(
            seq=seq,
            tick_ms=tick_ms,
            sample_count=sample_count,
            red=red,
            ir=ir,
            heart_rate_bpm=heart_rate_bpm,
            spo2_percent=spo2_percent,
            ratio=ratio,
            flags=flags,
            i2c_error_count=i2c_error_count,
        )


class CsvLogger:
    def __init__(self, path: Path | None) -> None:
        self.file = None
        self.writer: csv.writer | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.file = path.open("w", newline="", encoding="utf-8")
            self.writer = csv.writer(self.file)
            self.writer.writerow(
                [
                    "pc_time",
                    "seq",
                    "tick_ms",
                    "sample_count",
                    "red",
                    "ir",
                    "heart_rate_bpm",
                    "spo2_percent",
                    "ratio",
                    "initialized",
                    "present",
                    "finger_detected",
                    "spo2_ok",
                    "status",
                    "i2c_error_count",
                ]
            )

    def write(self, pkt: Max30102Packet) -> None:
        if self.writer is None:
            return
        self.writer.writerow(
            [
                time.time(),
                pkt.seq,
                pkt.tick_ms,
                pkt.sample_count,
                pkt.red,
                pkt.ir,
                pkt.heart_rate_bpm,
                pkt.spo2_percent,
                f"{pkt.ratio:.6f}",
                int(pkt.initialized),
                int(pkt.present),
                int(pkt.finger_detected),
                int(pkt.spo2_ok),
                pkt.status,
                pkt.i2c_error_count,
            ]
        )

    def close(self) -> None:
        if self.file is not None:
            self.file.close()


def send_command(ser: "serial.Serial", command: str, delay: float = 0.04) -> None:
    ser.write((command.rstrip() + "\n").encode("ascii"))
    ser.flush()
    time.sleep(delay)


def status_text(pkt: Max30102Packet, elapsed: float) -> str:
    return (
        f"[MAX] t={elapsed:6.1f}s seq={pkt.seq:06d} "
        f"present={int(pkt.present)} finger={int(pkt.finger_detected)} "
        f"spo2={pkt.spo2_percent:3d}% ok={int(pkt.spo2_ok)} "
        f"hr={pkt.heart_rate_bpm:3d}bpm ratio={pkt.ratio:5.3f} "
        f"red={pkt.red:6d} ir={pkt.ir:6d} i2c_err={pkt.i2c_error_count}"
    )


def run(args: argparse.Namespace) -> int:
    if serial is None:
        print("pyserial is required: python -m pip install pyserial", file=sys.stderr)
        return 2

    if not args.no_plot:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib is required for plotting: python -m pip install matplotlib", file=sys.stderr)
            return 2
    else:
        plt = None

    csv_logger = CsvLogger(Path(args.csv_out) if args.csv_out else None)
    parser = PacketParser()
    max_points = max(10, int(round(args.window_sec * 15)))

    times: deque[float] = deque(maxlen=max_points)
    red_values: deque[int] = deque(maxlen=max_points)
    ir_values: deque[int] = deque(maxlen=max_points)
    spo2_values: deque[int] = deque(maxlen=max_points)
    hr_values: deque[int] = deque(maxlen=max_points)
    ratio_values: deque[float] = deque(maxlen=max_points)
    finger_values: deque[int] = deque(maxlen=max_points)

    fig = axes = None
    lines = {}
    if plt is not None:
        plt.ion()
        fig, axes = plt.subplots(4, 1, figsize=(12, 8), sharex=True)
        fig.canvas.manager.set_window_title("MAX30102 Realtime Monitor")
        lines["red"], = axes[0].plot([], [], color="#d62728", label="RED raw")
        lines["ir"], = axes[0].plot([], [], color="#1f77b4", label="IR raw")
        axes[0].set_ylabel("ADC count")
        axes[0].legend(loc="upper right")
        axes[0].grid(True, alpha=0.25)

        lines["spo2"], = axes[1].plot([], [], color="#2ca02c", label="SpO2 %")
        axes[1].axhline(95, color="#ff7f0e", linestyle="--", linewidth=1, label="95%")
        axes[1].set_ylim(75, 102)
        axes[1].set_ylabel("SpO2 %")
        axes[1].legend(loc="upper right")
        axes[1].grid(True, alpha=0.25)

        lines["hr"], = axes[2].plot([], [], color="#9467bd", label="Heart rate bpm")
        axes[2].set_ylabel("bpm")
        axes[2].legend(loc="upper right")
        axes[2].grid(True, alpha=0.25)

        lines["ratio"], = axes[3].plot([], [], color="#8c564b", label="R ratio")
        lines["finger"], = axes[3].plot([], [], color="#17becf", label="finger detected")
        axes[3].set_ylabel("ratio / flag")
        axes[3].set_xlabel("seconds")
        axes[3].legend(loc="upper right")
        axes[3].grid(True, alpha=0.25)

    start = time.monotonic()
    last_draw = 0.0
    last_print = 0.0
    last_pkt: Max30102Packet | None = None
    received = 0

    ser = None
    try:
        ser = serial.Serial(args.port, args.baudrate, timeout=args.serial_timeout)
        time.sleep(args.open_delay)
        if args.ai != "keep":
            send_command(ser, f"AI {args.ai.upper()}")
        if args.led_mode != "keep":
            send_command(ser, f"LED {args.led_mode.upper()}")
        send_command(ser, "MAX ON")
        print("MAX30102 telemetry enabled. Press Ctrl+C to stop.")

        while True:
            now = time.monotonic()
            elapsed = now - start
            if args.duration and elapsed >= args.duration:
                break

            data = ser.read(args.read_chunk)
            if data:
                for pkt in parser.feed(data):
                    received += 1
                    last_pkt = pkt
                    t = elapsed
                    times.append(t)
                    red_values.append(pkt.red)
                    ir_values.append(pkt.ir)
                    spo2_values.append(pkt.spo2_percent if pkt.spo2_ok else 0)
                    hr_values.append(pkt.heart_rate_bpm)
                    ratio_values.append(pkt.ratio)
                    finger_values.append(1 if pkt.finger_detected else 0)
                    csv_logger.write(pkt)

            if last_pkt is not None and (elapsed - last_print) >= args.print_interval:
                last_print = elapsed
                print(status_text(last_pkt, elapsed), flush=True)

            if fig is not None and axes is not None and (elapsed - last_draw) >= args.draw_interval:
                last_draw = elapsed
                xs = list(times)
                lines["red"].set_data(xs, list(red_values))
                lines["ir"].set_data(xs, list(ir_values))
                lines["spo2"].set_data(xs, list(spo2_values))
                lines["hr"].set_data(xs, list(hr_values))
                lines["ratio"].set_data(xs, list(ratio_values))
                lines["finger"].set_data(xs, list(finger_values))
                for ax in axes:
                    ax.relim()
                    ax.autoscale_view(scalex=True, scaley=ax is not axes[1])
                axes[1].set_ylim(75, 102)
                if xs:
                    axes[-1].set_xlim(max(0.0, xs[-1] - args.window_sec), xs[-1] + 0.5)
                fig.suptitle(
                    f"MAX30102 telemetry | packets={received} "
                    f"audio_skip={parser.skipped_audio_packets} ai_skip={parser.skipped_ai_packets}"
                )
                fig.canvas.draw_idle()
                fig.canvas.flush_events()

            if fig is not None and not plt.fignum_exists(fig.number):
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if ser is not None and ser.is_open:
                send_command(ser, "MAX OFF", delay=0.0)
        except Exception:
            pass
        if ser is not None and ser.is_open:
            ser.close()
        csv_logger.close()

    if received == 0:
        print(
            "No MAX30102 telemetry packets were received. "
            "Flash the firmware that supports MAX ON/OFF, then try again.",
            file=sys.stderr,
        )
        return 1

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Realtime graph for STM32 MAX30102 RED/IR/SpO2 telemetry.")
    parser.add_argument("port", help="STM32 USB CDC COM port, e.g. COM4")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--duration", type=float, default=0.0, help="seconds to run; 0 means until Ctrl+C")
    parser.add_argument("--window-sec", type=float, default=20.0, help="plot window length")
    parser.add_argument("--draw-interval", type=float, default=0.10, help="plot refresh interval")
    parser.add_argument("--print-interval", type=float, default=1.0, help="console status interval")
    parser.add_argument("--read-chunk", type=int, default=DEFAULT_READ_CHUNK)
    parser.add_argument("--serial-timeout", type=float, default=0.05)
    parser.add_argument("--open-delay", type=float, default=0.8)
    parser.add_argument("--no-plot", action="store_true", help="print telemetry without opening graph")
    parser.add_argument("--csv-out", default="", help="optional CSV log path")
    parser.add_argument("--ai", choices=("keep", "on", "off"), default="keep", help="optional AI command after opening COM")
    parser.add_argument("--led-mode", choices=("keep", "raw", "stable", "off"), default="keep")
    return parser


def main() -> int:
    return run(build_arg_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
