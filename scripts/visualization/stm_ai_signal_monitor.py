# -*- coding: utf-8 -*-
# 파일 설명: STM32 내부 tiny MLP 예측 패킷과 raw 오디오 파형을 실시간으로 표시합니다.
r"""Realtime monitor for STM32 audio packets and on-board AI predictions.

Usage:
    python .\scripts\visualization\stm_ai_signal_monitor.py COM4 --sample-format pcm16
    python .\scripts\visualization\stm_ai_signal_monitor.py COM4 --sample-format pcm16 --print-ai
    python .\scripts\visualization\stm_ai_signal_monitor.py COM4 --sample-format pcm16 --no-plot --duration 8 --print-ai
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import os
import queue
import struct
import sys
import threading
import time

import numpy as np

try:
    import serial
except ImportError:
    serial = None

AUDIO_MAGIC = 0xAABBCCDD
AI_MAGIC = 0xA15A1EAF

AUDIO_HEADER_REST = struct.Struct("<IHH")
AI_PACKET_REST = struct.Struct("<IIHHII5f")
MAGIC_WORD = struct.Struct("<I")

SAMPLE_RATE = 16000
DEFAULT_BAUDRATE = 115200
DEFAULT_ADC_CENTER = 1551
DEFAULT_MAX_PACKET_SAMPLES = 512
DEFAULT_SERIAL_READ_CHUNK = 4096
DEFAULT_MIN_DRAW_INTERVAL = 0.05
DEFAULT_PLAYBACK_QUEUE_SEC = 0.75
AUDIO_FORMAT_ADC_U16 = 0
AUDIO_FORMAT_PCM16 = 1
SAMPLE_FORMAT_CHOICES = ("auto", "adc_u16", "pcm16")
UINT32_MOD = 0x100000000

LABELS = (
    "mouth_exhale",
    "mouth_inhale",
    "nasal_exhale",
    "nasal_inhale",
    "noise",
)

LABEL_TITLES = {
    "mouth_exhale": "mouth out",
    "mouth_inhale": "mouth in",
    "nasal_exhale": "nose out",
    "nasal_inhale": "nose in",
    "noise": "noise",
}

LABEL_COLORS = {
    "mouth_exhale": "#e0a000",
    "mouth_inhale": "#b452d6",
    "nasal_exhale": "#3a6df0",
    "nasal_inhale": "#00a6d6",
    "noise": "#777777",
}

LABEL_ICONS = {
    "mouth_exhale": "👄↗",
    "mouth_inhale": "👄↘",
    "nasal_exhale": "👃↗",
    "nasal_inhale": "👃↘",
    "noise": "🔇",
}

LABEL_ANSI_COLORS = {
    "mouth_exhale": "\033[38;5;208m",
    "mouth_inhale": "\033[38;5;171m",
    "nasal_exhale": "\033[38;5;39m",
    "nasal_inhale": "\033[38;5;44m",
    "noise": "\033[38;5;245m",
}

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[31m"


# 클래스 설명: 'AudioPacket' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
@dataclass(frozen=True)
class AudioPacket:
    seq: int
    adc: np.ndarray
    sample_format: int = AUDIO_FORMAT_ADC_U16


# 클래스 설명: 'AiPacket' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
@dataclass(frozen=True)
class AiPacket:
    seq: int
    audio_seq: int
    predicted: int
    status: int
    duration_ms: int
    input_blocks: int
    probabilities: np.ndarray


# 클래스 설명: 'RollingBuffer' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
class RollingBuffer:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def __init__(self, sample_rate: int, window_sec: float) -> None:
        self.max_samples = max(1, int(round(sample_rate * window_sec)))
        self.samples = np.zeros(self.max_samples, dtype=np.float32)
        self.write_index = 0
        self.total_samples = 0

    # 함수 설명: 'append' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def append(self, values: np.ndarray) -> None:
        if values.size == 0:
            return

        values = values.astype(np.float32, copy=False)
        if values.size >= self.max_samples:
            self.samples[:] = values[-self.max_samples :]
            self.write_index = 0
            self.total_samples += int(values.size)
            return

        end = self.write_index + values.size
        if end <= self.max_samples:
            self.samples[self.write_index : end] = values
        else:
            first = self.max_samples - self.write_index
            self.samples[self.write_index :] = values[:first]
            self.samples[: end % self.max_samples] = values[first:]

        self.write_index = end % self.max_samples
        self.total_samples += int(values.size)

    # 함수 설명: 'ordered' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def ordered(self, max_points: int = 0) -> tuple[np.ndarray, int]:
        if self.total_samples < self.max_samples:
            values = self.samples[: self.total_samples]
        else:
            values = np.concatenate((self.samples[self.write_index :], self.samples[: self.write_index]))

        step = 1
        if max_points > 0 and values.size > max_points:
            step = int(np.ceil(values.size / float(max_points)))
            values = values[::step]

        return values, step


class WaveFormatEx(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.c_ushort),
        ("nChannels", ctypes.c_ushort),
        ("nSamplesPerSec", ctypes.c_uint),
        ("nAvgBytesPerSec", ctypes.c_uint),
        ("nBlockAlign", ctypes.c_ushort),
        ("wBitsPerSample", ctypes.c_ushort),
        ("cbSize", ctypes.c_ushort),
    ]


class WaveHdr(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", ctypes.c_uint),
        ("dwBytesRecorded", ctypes.c_uint),
        ("dwUser", ctypes.c_void_p),
        ("dwFlags", ctypes.c_uint),
        ("dwLoops", ctypes.c_uint),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_void_p),
    ]


class LivePcmPlayer:
    CALLBACK_NULL = 0
    WAVE_FORMAT_PCM = 1
    WAVE_MAPPER = ctypes.c_uint(-1).value
    WHDR_DONE = 0x00000001

    def __init__(self, sample_rate: int, queue_sec: float = DEFAULT_PLAYBACK_QUEUE_SEC, gain: float = 1.0) -> None:
        if os.name != "nt":
            raise RuntimeError("--play-audio currently supports Windows only")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be greater than 0")
        if queue_sec <= 0:
            raise ValueError("queue_sec must be greater than 0")
        if gain <= 0:
            raise ValueError("gain must be greater than 0")

        self.sample_rate = int(sample_rate)
        self.gain = float(gain)
        self.dropped_buffers = 0
        self._handle = ctypes.c_void_p()
        self._closed = False
        max_buffers = max(2, int(round(queue_sec * self.sample_rate / float(DEFAULT_MAX_PACKET_SAMPLES))))
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=max_buffers)
        self._winmm = ctypes.WinDLL("winmm")
        self._configure_winmm()
        self._open_device()
        self._thread = threading.Thread(target=self._worker, name="stm-ai-audio-playback", daemon=True)
        self._thread.start()

    def _configure_winmm(self) -> None:
        self._winmm.waveOutOpen.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint,
            ctypes.POINTER(WaveFormatEx),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        self._winmm.waveOutOpen.restype = ctypes.c_uint
        self._winmm.waveOutPrepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(WaveHdr), ctypes.c_uint]
        self._winmm.waveOutPrepareHeader.restype = ctypes.c_uint
        self._winmm.waveOutWrite.argtypes = [ctypes.c_void_p, ctypes.POINTER(WaveHdr), ctypes.c_uint]
        self._winmm.waveOutWrite.restype = ctypes.c_uint
        self._winmm.waveOutUnprepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(WaveHdr), ctypes.c_uint]
        self._winmm.waveOutUnprepareHeader.restype = ctypes.c_uint
        self._winmm.waveOutReset.argtypes = [ctypes.c_void_p]
        self._winmm.waveOutReset.restype = ctypes.c_uint
        self._winmm.waveOutClose.argtypes = [ctypes.c_void_p]
        self._winmm.waveOutClose.restype = ctypes.c_uint

    def _raise_if_error(self, code: int, action: str) -> None:
        if int(code) != 0:
            raise RuntimeError(f"winmm {action} failed with code {code}")

    def _open_device(self) -> None:
        fmt = WaveFormatEx(self.WAVE_FORMAT_PCM, 1, self.sample_rate, self.sample_rate * 2, 2, 16, 0)
        code = self._winmm.waveOutOpen(
            ctypes.byref(self._handle),
            self.WAVE_MAPPER,
            ctypes.byref(fmt),
            None,
            None,
            self.CALLBACK_NULL,
        )
        self._raise_if_error(code, "waveOutOpen")

    def write(self, pcm: np.ndarray) -> None:
        if self._closed or pcm.size == 0:
            return
        if self.gain == 1.0:
            pcm_i16 = pcm.astype("<i2", copy=False)
        else:
            amplified = np.clip(pcm.astype(np.float32) * self.gain, -32768.0, 32767.0)
            pcm_i16 = amplified.astype("<i2")
        data = pcm_i16.tobytes()
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self.dropped_buffers += 1
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(data)
            except queue.Full:
                self.dropped_buffers += 1

    def _cleanup_done(self, pending: list[tuple[WaveHdr, ctypes.Array]]) -> list[tuple[WaveHdr, ctypes.Array]]:
        active: list[tuple[WaveHdr, ctypes.Array]] = []
        for header, buffer in pending:
            if header.dwFlags & self.WHDR_DONE:
                self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(header), ctypes.sizeof(header))
            else:
                active.append((header, buffer))
        return active

    def _worker(self) -> None:
        pending: list[tuple[WaveHdr, ctypes.Array]] = []
        try:
            while True:
                pending = self._cleanup_done(pending)
                try:
                    data = self._queue.get(timeout=0.02)
                except queue.Empty:
                    continue
                if data is None:
                    break
                buffer = ctypes.create_string_buffer(data)
                header = WaveHdr(ctypes.cast(buffer, ctypes.c_void_p), len(data), 0, None, 0, 0, None, None)
                self._raise_if_error(
                    self._winmm.waveOutPrepareHeader(self._handle, ctypes.byref(header), ctypes.sizeof(header)),
                    "waveOutPrepareHeader",
                )
                self._raise_if_error(
                    self._winmm.waveOutWrite(self._handle, ctypes.byref(header), ctypes.sizeof(header)),
                    "waveOutWrite",
                )
                pending.append((header, buffer))
            while pending:
                pending = self._cleanup_done(pending)
                time.sleep(0.01)
        finally:
            for header, _buffer in pending:
                self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(header), ctypes.sizeof(header))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(None)
        self._thread.join(timeout=2.0)
        self._winmm.waveOutReset(self._handle)
        self._winmm.waveOutClose(self._handle)


# 함수 설명: 실행 환경이나 출력 형식을 현재 작업에 맞게 설정합니다.
def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def should_use_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never" or os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def colorize(text: str, color: str, enabled: bool, *, bold: bool = False, dim: bool = False) -> str:
    if not enabled:
        return text

    prefix = ""
    if bold:
        prefix += ANSI_BOLD
    if dim:
        prefix += ANSI_DIM
    prefix += color
    return f"{prefix}{text}{ANSI_RESET}"


# 함수 설명: 보드나 출력 장치로 제어 명령 또는 데이터 패킷을 전송합니다.
def send_board_ai_inference_command(ser: serial.Serial, mode: str) -> None:
    if mode == "keep":
        return

    command = "AI ON\n" if mode == "on" else "AI OFF\n"
    ser.write(command.encode("ascii"))
    ser.flush()
    time.sleep(0.05)


def send_board_led_mode_command(ser: serial.Serial, mode: str) -> None:
    if mode == "keep":
        return

    if mode == "raw":
        command = "LED RAW\n"
    elif mode == "off":
        command = "LED OFF\n"
    else:
        command = "LED STABLE\n"
    ser.write(command.encode("ascii"))
    ser.flush()
    time.sleep(0.05)


def resolve_packet_sample_format(packet: AudioPacket, requested: str) -> int:
    if requested == "pcm16":
        return AUDIO_FORMAT_PCM16
    if requested == "adc_u16":
        return AUDIO_FORMAT_ADC_U16
    return packet.sample_format


def packet_to_centered_debug(packet: AudioPacket, requested: str, adc_center: float, pcm16_gain: float) -> np.ndarray:
    sample_format = resolve_packet_sample_format(packet, requested)
    if sample_format == AUDIO_FORMAT_PCM16:
        return packet.adc.view("<i2").astype(np.float32) * float(pcm16_gain)
    return packet.adc.astype(np.float32) - float(adc_center)


def adc_to_pcm_i16(adc: np.ndarray, adc_center: float) -> np.ndarray:
    centered = adc.astype(np.float32) - float(adc_center)
    pcm = np.clip(centered, -32768, 32767)
    return pcm.astype("<i2")


def apply_pcm16_gain_i16(pcm: np.ndarray, gain: float) -> np.ndarray:
    if float(gain) == 1.0:
        return pcm.astype("<i2", copy=True)
    scaled = np.rint(pcm.astype(np.float32) * float(gain))
    scaled = np.clip(scaled, -32768, 32767)
    return scaled.astype("<i2")


def packet_to_pcm_i16(packet: AudioPacket, requested: str, adc_center: float, pcm16_gain: float) -> np.ndarray:
    sample_format = resolve_packet_sample_format(packet, requested)
    if sample_format == AUDIO_FORMAT_PCM16:
        return apply_pcm16_gain_i16(packet.adc.view("<i2"), pcm16_gain)
    return adc_to_pcm_i16(packet.adc, adc_center)


# 클래스 설명: 'MixedPacketReceiver' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
class MixedPacketReceiver:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def __init__(self, ser: serial.Serial, max_packet_samples: int, read_chunk_size: int) -> None:
        self.ser = ser
        self.max_packet_samples = max_packet_samples
        self.read_chunk_size = max(16, int(read_chunk_size))
        self.buffer = bytearray()

    def read_from_serial(self, min_size: int) -> None:
        waiting = int(getattr(self.ser, "in_waiting", 0) or 0)
        read_size = max(int(min_size), min(waiting, self.read_chunk_size))
        chunk = self.ser.read(read_size)
        if chunk:
            self.buffer.extend(chunk)

    # 함수 설명: 파일, 시리얼, 모델, 설정 등 외부 입력을 읽어 메모리에 올립니다.
    def read_exact(self, size: int, timeout_sec: float = 2.0) -> bytes:
        deadline = time.monotonic() + timeout_sec

        while len(self.buffer) < size:
            before = len(self.buffer)
            self.read_from_serial(size - len(self.buffer))
            if len(self.buffer) > before:
                deadline = time.monotonic() + timeout_sec
                continue

            if time.monotonic() >= deadline:
                raise TimeoutError(f"serial timeout while reading {size} bytes")

        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    # 함수 설명: 파일, 시리얼, 모델, 설정 등 외부 입력을 읽어 메모리에 올립니다.
    def read_magic(self, timeout_sec: float = 2.0) -> int:
        deadline = time.monotonic() + timeout_sec
        while True:
            while len(self.buffer) < 4:
                before = len(self.buffer)
                self.read_from_serial(4 - len(self.buffer))
                if len(self.buffer) > before:
                    deadline = time.monotonic() + timeout_sec
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError("serial timeout while waiting for packet magic")

            magic = MAGIC_WORD.unpack(self.buffer[:4])[0]
            if magic in (AUDIO_MAGIC, AI_MAGIC):
                del self.buffer[:4]
                return magic

            del self.buffer[0]
            deadline = time.monotonic() + timeout_sec

    # 함수 설명: 파일, 시리얼, 모델, 설정 등 외부 입력을 읽어 메모리에 올립니다.
    def read_packet(self) -> AudioPacket | AiPacket:
        magic = self.read_magic()

        if magic == AUDIO_MAGIC:
            rest = self.read_exact(AUDIO_HEADER_REST.size)
            seq, samples, reserved = AUDIO_HEADER_REST.unpack(rest)
            if samples <= 0 or samples > self.max_packet_samples:
                raise ValueError(f"invalid audio packet sample count: {samples}")

            payload = self.read_exact(samples * 2)
            adc = np.frombuffer(payload, dtype="<u2").copy()
            return AudioPacket(seq=seq, adc=adc, sample_format=reserved)

        rest = self.read_exact(AI_PACKET_REST.size)
        seq, audio_seq, predicted, status, duration_ms, input_blocks, *probabilities = AI_PACKET_REST.unpack(rest)
        return AiPacket(
            seq=seq,
            audio_seq=audio_seq,
            predicted=predicted,
            status=status,
            duration_ms=duration_ms,
            input_blocks=input_blocks,
            probabilities=np.asarray(probabilities, dtype=np.float32),
        )


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def format_label(label: str, color_enabled: bool) -> str:
    icon = LABEL_ICONS.get(label, "•")
    title = LABEL_TITLES.get(label, label)
    text = f"{icon} {title}"
    return colorize(text, LABEL_ANSI_COLORS.get(label, ""), color_enabled, bold=True)


def format_ai_packet(packet: AiPacket, *, color_enabled: bool, show_probabilities: bool = False) -> str:
    if packet.status != 0:
        status = colorize(f"status={packet.status}", ANSI_RED, color_enabled, bold=True)
        return f"AI#{packet.seq:06d} ❌ {status} audio={packet.audio_seq} dur={packet.duration_ms}ms"

    stable_label = LABELS[packet.predicted] if packet.predicted < len(LABELS) else f"label_{packet.predicted}"
    raw_predicted = int(np.argmax(packet.probabilities))
    raw_label = LABELS[raw_predicted] if raw_predicted < len(LABELS) else f"label_{raw_predicted}"
    raw_confidence = float(packet.probabilities[raw_predicted])
    match_icon = "✅" if raw_predicted == packet.predicted else "⚠️"

    line = (
        f"AI#{packet.seq:06d} {match_icon} "
        f"top={format_label(raw_label, color_enabled)} {raw_confidence:.1%} "
        f"| stable={format_label(stable_label, color_enabled)} "
        f"| audio={packet.audio_seq} "
        f"| dur={packet.duration_ms}ms"
    )
    if show_probabilities:
        probs = " ".join(f"{LABEL_TITLES[LABELS[i]]}={packet.probabilities[i]:.3f}" for i in range(len(LABELS)))
        line = f"{line} | {colorize(probs, ANSI_DIM, color_enabled, dim=True)}"
    return line


# 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
def update_plot(
    waveform_line,
    waveform_axis,
    bars,
    title_text,
    rolling: RollingBuffer,
    last_ai: AiPacket | None,
    sample_rate: int,
    max_plot_points: int,
) -> None:
    waveform, sample_step = rolling.ordered(max_points=max_plot_points)
    if waveform.size:
        seconds = (np.arange(waveform.size, dtype=np.float32) * float(sample_step)) / float(sample_rate)
        seconds -= seconds[-1]
        waveform_line.set_data(seconds, waveform)
        waveform_axis.set_xlim(float(seconds[0]), 0.0)
        limit = max(50.0, float(np.max(np.abs(waveform))) * 1.05)
        waveform_axis.set_ylim(-limit, limit)

    if last_ai is not None and last_ai.status == 0:
        predicted = last_ai.predicted
        raw_predicted = int(np.argmax(last_ai.probabilities))
        for idx, bar in enumerate(bars):
            value = float(last_ai.probabilities[idx])
            bar.set_height(value)
            label = LABELS[idx]
            if idx == predicted:
                bar.set_color(LABEL_COLORS.get(label, "#999999"))
            elif idx == raw_predicted:
                bar.set_color("#a9b4c4")
            else:
                bar.set_color("#dddddd")

        label = LABELS[predicted] if predicted < len(LABELS) else f"label_{predicted}"
        raw_label = LABELS[raw_predicted] if raw_predicted < len(LABELS) else f"label_{raw_predicted}"
        stable_current_prob = (
            float(last_ai.probabilities[predicted])
            if predicted < len(last_ai.probabilities)
            else float("nan")
        )
        raw_confidence = float(last_ai.probabilities[raw_predicted])
        title_text.set_text(
            f"STM32 AI stable: {LABEL_TITLES.get(label, label)} "
            f"(now {stable_current_prob:.1%}) | raw: {LABEL_TITLES.get(raw_label, raw_label)} {raw_confidence:.1%}  "
            f"(ai_seq={last_ai.seq}, audio_seq={last_ai.audio_seq})"
        )
    elif last_ai is not None:
        title_text.set_text(f"STM32 AI error: status={last_ai.status} ai_seq={last_ai.seq}")


# 함수 설명: 선택된 작업 흐름을 순서대로 실행하고 하위 단계를 호출합니다.
def run_monitor(args: argparse.Namespace) -> None:
    if serial is None:
        raise RuntimeError("pyserial is required. Install it with: pip install pyserial")

    ser = serial.Serial(args.port, args.baudrate, timeout=0.05)
    send_board_ai_inference_command(ser, args.ai_inference)
    send_board_led_mode_command(ser, args.led_mode)
    ser.reset_input_buffer()
    receiver = MixedPacketReceiver(ser, args.max_packet_samples, args.serial_read_chunk)
    rolling = RollingBuffer(args.sample_rate, args.window_sec)

    packet_count = 0
    audio_count = 0
    expected_audio_seq: int | None = None
    audio_dropped = 0
    ai_count = 0
    last_ai: AiPacket | None = None
    ai_durations_ms: list[int] = []
    start_time = time.monotonic()
    last_draw = 0.0
    effective_draw_interval = max(float(args.draw_interval), float(args.min_draw_interval))
    color_enabled = should_use_color(args.color)
    audio_player: LivePcmPlayer | None = None

    print(
        f"STM32 AI monitor: ai={args.ai_inference}, led={args.led_mode}, "
        f"sample_format={args.sample_format}, pcm16_gain={args.pcm16_gain:g}, "
        f"play_audio={'on' if args.play_audio else 'off'}"
    )

    fig = None
    if not args.no_plot:
        import matplotlib.pyplot as plt

        fig, (waveform_axis, prob_axis) = plt.subplots(2, 1, figsize=(11, 7), height_ratios=(2, 1))
        waveform_line, = waveform_axis.plot([], [], color="#2d6cdf", linewidth=1.0)
        waveform_axis.set_title("STM32 raw waveform")
        waveform_axis.set_xlabel("seconds")
        waveform_axis.set_ylabel("sample")
        waveform_axis.grid(True, alpha=0.25)

        bars = prob_axis.bar(
            range(len(LABELS)),
            np.zeros(len(LABELS)),
            color=[LABEL_COLORS[label] for label in LABELS],
        )
        prob_axis.set_ylim(0.0, 1.0)
        prob_axis.set_ylabel("probability")
        prob_axis.set_xticks(range(len(LABELS)))
        prob_axis.set_xticklabels([LABEL_TITLES[label] for label in LABELS], rotation=15, ha="right")
        prob_axis.grid(True, axis="y", alpha=0.25)
        title_text = fig.suptitle("Waiting for STM32 AI packets...")
        fig.tight_layout()
        plt.show(block=False)
    else:
        plt = None
        waveform_line = waveform_axis = bars = title_text = None

    try:
        if args.play_audio:
            audio_player = LivePcmPlayer(
                sample_rate=args.sample_rate,
                queue_sec=args.playback_queue_sec,
                gain=args.playback_gain,
            )

        while True:
            if args.duration and (time.monotonic() - start_time) >= args.duration:
                break

            if fig is not None and not plt.fignum_exists(fig.number):
                break

            try:
                packet = receiver.read_packet()
            except (TimeoutError, ValueError) as exc:
                if args.verbose:
                    print(f"skip packet: {exc}")
                continue

            packet_count += 1
            if isinstance(packet, AudioPacket):
                if expected_audio_seq is not None and packet.seq != expected_audio_seq:
                    gap = (packet.seq - expected_audio_seq) % UINT32_MOD
                    if gap > 0:
                        audio_dropped += gap
                        if args.verbose:
                            print(f"audio seq jump: expected={expected_audio_seq}, got={packet.seq}, missing={gap}")
                expected_audio_seq = (packet.seq + 1) % UINT32_MOD
                audio_count += 1
                if audio_player is not None:
                    pcm = packet_to_pcm_i16(packet, args.sample_format, args.adc_center, args.pcm16_gain)
                    audio_player.write(pcm)
                if fig is not None:
                    centered = packet_to_centered_debug(packet, args.sample_format, args.adc_center, args.pcm16_gain)
                    rolling.append(centered)
            else:
                last_ai = packet
                ai_count += 1
                ai_durations_ms.append(int(packet.duration_ms))
                if args.print_ai:
                    print(
                        format_ai_packet(
                            packet,
                            color_enabled=color_enabled,
                            show_probabilities=args.print_ai_probs,
                        )
                    )

            now = time.monotonic()
            if fig is not None and (now - last_draw) >= effective_draw_interval:
                update_plot(
                    waveform_line,
                    waveform_axis,
                    bars,
                    title_text,
                    rolling,
                    last_ai,
                    args.sample_rate,
                    args.max_plot_points,
                )
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                last_draw = now

    except KeyboardInterrupt:
        pass
    finally:
        if audio_player is not None:
            audio_player.close()
        ser.close()

    elapsed = max(1e-6, time.monotonic() - start_time)
    print(
        f"received packets={packet_count}, audio_packets={audio_count}, ai_packets={ai_count}, "
        f"audio_dropped={audio_dropped}, elapsed={elapsed:.1f}s, ai_rate={ai_count / elapsed:.2f}/s"
    )
    if ai_durations_ms:
        durations = np.asarray(ai_durations_ms, dtype=np.float32)
        print(
            "ai_duration_ms="
            f"mean={float(np.mean(durations)):.1f}, "
            f"p50={float(np.percentile(durations, 50)):.1f}, "
            f"p95={float(np.percentile(durations, 95)):.1f}, "
            f"max={int(np.max(durations))}"
        )
    if audio_player is not None:
        print(f"playback_dropped={audio_player.dropped_buffers}")


# 함수 설명: 명령행 옵션을 정의하고 사용자가 입력한 인자를 파싱합니다.
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor STM32 raw audio and on-board AI prediction packets.")
    parser.add_argument("port", help="serial port, e.g. COM4")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE)
    parser.add_argument("--adc-center", type=float, default=DEFAULT_ADC_CENTER)
    parser.add_argument(
        "--sample-format",
        choices=SAMPLE_FORMAT_CHOICES,
        default="auto",
        help="audio payload format: auto uses packet reserved field, adc_u16 is MAX9814 ADC, pcm16 is I2S PCM",
    )
    parser.add_argument("--pcm16-gain", type=float, default=1.0, help="display gain applied only to pcm16/I2S waveform")
    parser.add_argument("--window-sec", type=float, default=1.5)
    parser.add_argument("--duration", type=float, default=0.0, help="stop after N seconds; 0 means run until closed")
    parser.add_argument("--draw-interval", type=float, default=0.03)
    parser.add_argument(
        "--min-draw-interval",
        type=float,
        default=DEFAULT_MIN_DRAW_INTERVAL,
        help="minimum GUI redraw interval; keeps plotting from starving serial receive",
    )
    parser.add_argument("--max-plot-points", type=int, default=2000, help="maximum waveform points drawn per refresh")
    parser.add_argument("--max-packet-samples", type=int, default=DEFAULT_MAX_PACKET_SAMPLES)
    parser.add_argument(
        "--serial-read-chunk",
        type=int,
        default=DEFAULT_SERIAL_READ_CHUNK,
        help="maximum bytes drained from the OS serial buffer per read",
    )
    parser.add_argument("--print-ai", action="store_true", help="print compact STM32 AI top-class prediction lines")
    parser.add_argument(
        "--print-ai-probs",
        action="store_true",
        help="append all class probabilities to --print-ai output for debugging",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="ANSI color mode for --print-ai output",
    )
    parser.add_argument(
        "--play-audio",
        action="store_true",
        help="play received audio packets while monitoring STM32 AI output; use headphones to avoid feedback",
    )
    parser.add_argument(
        "--playback-gain",
        type=float,
        default=1.0,
        help="monitor-only playback gain applied after --pcm16-gain; does not affect STM32 inference",
    )
    parser.add_argument(
        "--playback-queue-sec",
        type=float,
        default=DEFAULT_PLAYBACK_QUEUE_SEC,
        help="maximum live playback queue length before old audio buffers are dropped",
    )
    parser.add_argument("--no-plot", action="store_true", help="run without matplotlib GUI")
    parser.add_argument(
        "--ai-inference",
        choices=("on", "off", "keep"),
        default="on",
        help="send AI ON/OFF to the board after opening COM; default on for STM AI monitoring",
    )
    parser.add_argument(
        "--led-mode",
        choices=("off", "raw", "stable", "keep"),
        default="off",
        help="send LED OFF/RAW/STABLE to the board; off is best for noise/model checks, raw checks LED mapping",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


# 함수 설명: 스크립트 진입점으로 인자를 읽고 전체 실행 흐름을 호출합니다.
def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        run_monitor(args)
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
