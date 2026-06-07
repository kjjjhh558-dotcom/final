# -*- coding: utf-8 -*-
"""STM32 오디오 스트림과 PC 측 실시간 검증 결과를 그래프로 확인합니다.

USB CDC 오디오 패킷을 읽어 raw/filtered 파형, RMS/peak-to-peak, 선택적 PC 모델 예측을 표시하고 WAV 저장이나 오디오 재생도 지원합니다."""

# 파일 설명: STM32 raw 오디오와 PC 모델 예측을 실시간 그래프로 확인합니다.
#
# realtime_signal_monitor.py
#
# 목적:
#   STM32F407 + MAX9814에서 USB CDC로 들어오는 ADC 오디오 스트림을 실시간 그래프로
#   확인합니다. 데이터 수집 전에 마이크 입력이 정상인지 확인하거나, 학습된 모델을
#   함께 넣어 실시간 분류 결과와 신호 상태를 한 화면에서 검증할 수 있습니다.
#
# 실행 예:
#   1. 원시 오디오 입력 확인:
#        python .\scripts\visualization\realtime_signal_monitor.py COM5
#
#   2. 원시 입력을 WAV로 저장하면서 확인:
#        python .\scripts\visualization\realtime_signal_monitor.py COM5 --save-wav .\artifacts\predictions\live_check.wav
#
#   3. 모델 실시간 검증 + 그래프:
#
# 그래프 구성:
#   - Raw ADC centered waveform: adc - adc_center 값
#   - Filtered waveform: 50~2500 Hz causal Butterworth IIR 통과 후 파형
#   - Level history: filtered RMS와 raw ADC peak-to-peak 추이
#
# 주의:
#   COM 포트는 보통 한 프로그램만 열 수 있습니다. 이 스크립트를 실행 중이면
#   collect_breath_dataset.py 또는 realtime_validate.py를 동시에 같은 COM 포트로
#   실행할 수 없습니다.

from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import struct
import sys
import time
import wave

import numpy as np
import threading

try:
    import serial

    SerialException = serial.SerialException
except ImportError:
    serial = None

    # 클래스 설명: 'SerialException' 예외 상황을 표현하는 전용 오류 타입입니다.
    class SerialException(Exception):
        pass

plt = None

signal = None


MAGIC = 0xAABBCCDD
HEADER_SIZE = 12
UINT32_MOD = 0x100000000
AUDIO_FORMAT_ADC_U16 = 0
AUDIO_FORMAT_PCM16 = 1
SAMPLE_FORMAT_CHOICES = ("auto", "adc_u16", "pcm16")

SAMPLE_RATE = 16000
DEFAULT_BAUDRATE = 115200
DEFAULT_ADC_CENTER = 1551
DEFAULT_PCM_GAIN = 16.0
DEFAULT_PACKET_SAMPLES = 512
DEFAULT_HALF_BUFFER_SAMPLES = 4000

BANDPASS_LOW_HZ = 50.0
BANDPASS_HIGH_HZ = 2500.0
BANDPASS_ORDER = 4

FRAME_SIZE = 1024
HOP_SIZE = 512

LABEL_NAMES = {
    "nasal_inhale": "코 들숨",
    "nasal_exhale": "코 날숨",
    "mouth_inhale": "입 들숨",
    "mouth_exhale": "입 날숨",
    "noise": "노이즈",
}

LABEL_ICONS = {
    "nasal_inhale": "[N-IN]",
    "nasal_exhale": "[N-OUT]",
    "mouth_inhale": "[M-IN]",
    "mouth_exhale": "[M-OUT]",
    "noise": "[NOISE]",
}

LABEL_COLORS = {
    "nasal_inhale": "#00a6d6",
    "nasal_exhale": "#3a6df0",
    "mouth_inhale": "#b452d6",
    "mouth_exhale": "#e0a000",
    "noise": "#777777",
}


# 클래스 설명: 'DependencyError' 예외 상황을 표현하는 전용 오류 타입입니다.
class DependencyError(RuntimeError):
    """DependencyError는 선택 의존성이 없을 때 사용자에게 설치 안내를 주기 위한 전용 예외입니다."""
    pass


# 클래스 설명: 'AudioPacket' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
@dataclass(frozen=True)
class AudioPacket:
    """AudioPacket는 펌웨어나 센서에서 받은 한 개 패킷의 필드를 묶어 전달하는 데이터 구조입니다."""
    seq: int
    samples: int
    adc: np.ndarray
    sample_format: int = AUDIO_FORMAT_ADC_U16


# 클래스 설명: 'MonitorStats' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
@dataclass
class MonitorStats:
    """MonitorStats는 실시간 처리 중 누적되는 상태값과 통계를 보관합니다."""
    total_packets: int = 0
    dropped_packets: int = 0
    inserted_samples: int = 0
    received_samples: int = 0
    expected_seq: int | None = None
    short_packet_mod: int | None = None
    start_time: float = 0.0
    last_status_time: float = 0.0
    last_status_packets: int = 0
    packets_per_sec: float = 0.0


# 클래스 설명: 'PredictionState' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
@dataclass
class PredictionState:
    """PredictionState는 실시간 처리 중 누적되는 상태값과 통계를 보관합니다."""
    frame_index: int = 0
    pred_label: str = ""
    confidence: float = float("nan")
    voted_label: str = ""
    vote_ratio: float = 0.0
    mean_confidence: float = float("nan")
    probabilities: dict[str, float] | None = None
    snr_total_db: float | None = None
    spectral_subtracted_energy: float = 0.0


# 함수 설명: 실행 환경이나 출력 형식을 현재 작업에 맞게 설정합니다.
def configure_utf8_stdio() -> None:
    """실행 환경, 출력 인코딩, 라이브러리 옵션처럼 본 처리 전에 필요한 설정을 적용합니다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


# 함수 설명: 실행 환경이나 출력 형식을 현재 작업에 맞게 설정합니다.
def send_board_ai_inference_command(ser: serial.Serial, mode: str) -> None:
    """STM32나 보조 보드로 한 줄 제어 명령을 보내고 전송 버퍼를 비웁니다."""
    if mode == "keep":
        return

    command = "AI ON\n" if mode == "on" else "AI OFF\n"
    ser.write(command.encode("ascii"))
    ser.flush()
    time.sleep(0.05)


def configure_matplotlib_font(enabled: bool) -> None:
    """실행 환경, 출력 인코딩, 라이브러리 옵션처럼 본 처리 전에 필요한 설정을 적용합니다."""
    if not enabled or plt is None:
        return

    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in ("Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"):
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False


# 함수 설명: 파일, 시리얼, 모델, 설정 등 외부 입력을 읽어 메모리에 올립니다.
def read_exact(ser: serial.Serial, size: int, timeout_sec: float = 2.0) -> bytes:
    """시리얼 포트에서 지정한 byte 수가 모일 때까지 읽고 timeout 시 오류를 냅니다."""
    deadline = time.monotonic() + timeout_sec
    chunks: list[bytes] = []
    received = 0

    while received < size:
        chunk = ser.read(size - received)
        if chunk:
            chunks.append(chunk)
            received += len(chunk)
            continue

        if time.monotonic() >= deadline:
            raise TimeoutError(f"serial timeout while reading {size} bytes")

    return b"".join(chunks)


# 클래스 설명: 'PacketReceiver' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
class PacketReceiver:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    """PacketReceiver는 시리얼 byte stream에서 필요한 packet을 동기화하고 파싱합니다."""
    def __init__(self, ser: serial.Serial, max_packet_samples: int) -> None:
        """PacketReceiver 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
        self.ser = ser
        self.max_packet_samples = max_packet_samples

    # 함수 설명: 입력 스트림이나 목록에서 필요한 위치와 대상을 찾아 동기화합니다.
    def sync_to_magic(self) -> None:
        """시리얼 stream에서 packet 시작을 나타내는 magic word까지 byte를 버리며 동기화합니다."""
        sync = bytearray()
        while True:
            byte = self.ser.read(1)
            if not byte:
                continue

            sync.append(byte[0])
            if len(sync) > 4:
                del sync[0]

            if len(sync) == 4 and struct.unpack("<I", sync)[0] == MAGIC:
                return

    # 함수 설명: 파일, 시리얼, 모델, 설정 등 외부 입력을 읽어 메모리에 올립니다.
    def read_packet(self) -> AudioPacket:
        """동기화된 시리얼 stream에서 header와 payload를 읽어 packet 객체로 변환합니다."""
        self.sync_to_magic()
        rest = read_exact(self.ser, HEADER_SIZE - 4)
        seq, samples, reserved = struct.unpack("<IHH", rest)

        if samples <= 0 or samples > self.max_packet_samples:
            raise ValueError(f"invalid packet sample count: {samples}")

        payload = read_exact(self.ser, samples * 2)
        adc = np.frombuffer(payload, dtype="<u2").copy()
        sample_format = AUDIO_FORMAT_PCM16 if reserved == AUDIO_FORMAT_PCM16 else AUDIO_FORMAT_ADC_U16
        return AudioPacket(seq=seq, samples=samples, adc=adc, sample_format=sample_format)


# 클래스 설명: 'WavPcmWriter' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
class WavPcmWriter:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    """WavPcmWriter는 수집 또는 모니터링 결과를 파일로 안전하게 기록합니다."""
    def __init__(self, path: Path, sample_rate: int) -> None:
        """WavPcmWriter 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.wav = wave.open(str(path), "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(sample_rate)

    # 함수 설명: 계산된 결과나 데이터를 파일 또는 출력 장치에 저장합니다.
    def write(self, pcm: np.ndarray) -> None:
        """WavPcmWriter.write는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        if pcm.size:
            self.wav.writeframes(pcm.astype("<i2", copy=False).tobytes())

    # 함수 설명: 'close' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def close(self) -> None:
        """열어 둔 파일, 오디오 장치, 스레드 등 외부 자원을 정리합니다."""
        self.wav.close()


# 클래스 설명: sounddevice OutputStream을 통해 PCM16 오디오를 실시간으로 재생합니다.
class AudioPlayer:
    """AudioPlayer는 수신한 PCM 오디오를 PC에서 실시간 재생하기 위한 보조 구성 요소입니다."""
    def __init__(self, sample_rate: int, max_buffered_chunks: int = 16) -> None:
        """AudioPlayer 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
        self._rate = sample_rate
        self._chunks: deque[np.ndarray] = deque()
        self._lock = threading.Lock()
        self._max_chunks = max_buffered_chunks
        self._leftover = np.zeros(0, dtype=np.int16)
        self._stream = None

    def start(self) -> None:
        """AudioPlayer.start는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise DependencyError(
                "sounddevice is required for audio playback. Install with: pip install sounddevice"
            ) from exc
        self._stream = sd.OutputStream(
            samplerate=self._rate,
            channels=1,
            dtype="int16",
            callback=self._callback,
            latency="low",
        )
        self._stream.start()

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        """AudioPlayer._callback는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        filled = 0
        with self._lock:
            while filled < frames:
                if self._leftover.size == 0:
                    if not self._chunks:
                        break
                    self._leftover = self._chunks.popleft()
                n = min(frames - filled, self._leftover.size)
                outdata[filled : filled + n, 0] = self._leftover[:n]
                self._leftover = self._leftover[n:]
                filled += n
        if filled < frames:
            outdata[filled:, 0] = 0

    def push(self, pcm_i16: np.ndarray) -> None:
        """AudioPlayer.push는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        chunk = np.asarray(pcm_i16, dtype=np.int16).copy()
        with self._lock:
            if len(self._chunks) >= self._max_chunks:
                self._chunks.popleft()
            self._chunks.append(chunk)

    def close(self) -> None:
        """열어 둔 파일, 오디오 장치, 스레드 등 외부 자원을 정리합니다."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


# 클래스 설명: 'RollingSignalBuffer' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
class RollingSignalBuffer:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    """RollingSignalBuffer는 이 모듈에서 관련 데이터와 동작을 묶어 관리하는 구성 요소입니다."""
    def __init__(self, sample_rate: int, window_sec: float) -> None:
        """RollingSignalBuffer 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
        self.sample_rate = sample_rate
        self.window_sec = window_sec
        self.max_samples = max(1, int(round(sample_rate * window_sec)))
        self.raw_centered = np.zeros(self.max_samples, dtype=np.float32)
        self.filtered = np.zeros(self.max_samples, dtype=np.float32)
        self.total_samples = 0
        self.write_index = 0

    # 함수 설명: 'append' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def append(self, raw_centered: np.ndarray, filtered: np.ndarray) -> None:
        """RollingSignalBuffer.append는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        n = int(min(raw_centered.size, filtered.size))
        if n <= 0:
            return

        raw = raw_centered[-n:].astype(np.float32, copy=False)
        fil = filtered[-n:].astype(np.float32, copy=False)

        if n >= self.max_samples:
            self.raw_centered[:] = raw[-self.max_samples :]
            self.filtered[:] = fil[-self.max_samples :]
            self.write_index = 0
        else:
            end = self.write_index + n
            if end <= self.max_samples:
                self.raw_centered[self.write_index : end] = raw
                self.filtered[self.write_index : end] = fil
            else:
                first = self.max_samples - self.write_index
                self.raw_centered[self.write_index :] = raw[:first]
                self.raw_centered[: end % self.max_samples] = raw[first:]
                self.filtered[self.write_index :] = fil[:first]
                self.filtered[: end % self.max_samples] = fil[first:]
            self.write_index = end % self.max_samples

        self.total_samples += n

    # 함수 설명: 'display_view' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def display_view(self, max_points: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """RollingSignalBuffer.display_view는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        count = int(min(self.total_samples, self.max_samples))
        if count <= 0:
            return (
                np.zeros(1, dtype=np.float32),
                np.zeros(1, dtype=np.float32),
                np.zeros(1, dtype=np.float32),
            )

        step = max(1, int(np.ceil(count / max(1, max_points))))

        if self.total_samples < self.max_samples:
            raw = self.raw_centered[:count:step]
            fil = self.filtered[:count:step]
        else:
            idx = (np.arange(0, count, step) + self.write_index) % self.max_samples
            raw = self.raw_centered[idx]
            fil = self.filtered[idx]

        duration_sec = (count - 1) / self.sample_rate
        time_axis = np.linspace(-duration_sec, 0.0, raw.size, dtype=np.float32)
        return time_axis, raw, fil


# 클래스 설명: 'RealtimeSignalPlotter' 동작에 필요한 상태와 메서드를 묶는 클래스입니다.
class RealtimeSignalPlotter:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    """RealtimeSignalPlotter는 이 모듈에서 관련 데이터와 동작을 묶어 관리하는 구성 요소입니다."""
    def __init__(self, args: argparse.Namespace, model_labels: list[str]) -> None:
        """RealtimeSignalPlotter 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
        global plt
        if plt is None:
            import matplotlib

            matplotlib.rcParams["path.simplify"] = True
            matplotlib.rcParams["path.simplify_threshold"] = 1.0
            matplotlib.rcParams["agg.path.chunksize"] = 10000
            import matplotlib.pyplot as imported_plt

            plt = imported_plt

        configure_matplotlib_font(args.korean_font)
        plt.ion()

        self.args = args
        self.model_labels = model_labels
        row_count = 4 if model_labels else 3
        self.fig, axes = plt.subplots(row_count, 1, figsize=(11, 7.2))
        self.axes = np.atleast_1d(axes).tolist()
        self.last_ylim_update = 0.0

        self.raw_line, = self.axes[0].plot([], [], color="#1f77b4", linewidth=1.0)
        self.filtered_line, = self.axes[1].plot([], [], color="#2ca02c", linewidth=1.0)
        self.rms_line, = self.axes[2].plot([], [], color="#d62728", linewidth=1.4, label="filtered RMS")
        self.p2p_line, = self.axes[2].plot([], [], color="#9467bd", linewidth=1.0, label="ADC p2p / 4096")
        self.snr_line, = self.axes[2].plot([], [], color="#ff7f0e", linewidth=1.2, label="SNR / 30 dB")
        self.sub_energy_line, = self.axes[2].plot([], [], color="#17becf", linewidth=1.0, label="sub energy norm")

        self.level_times: deque[float] = deque(maxlen=600)
        self.level_rms: deque[float] = deque(maxlen=600)
        self.level_p2p_norm: deque[float] = deque(maxlen=600)
        self.level_snr_norm: deque[float] = deque(maxlen=600)
        self.level_sub_energy: deque[float] = deque(maxlen=600)

        self.axes[0].set_title("Raw ADC centered waveform")
        self.axes[0].set_ylabel("ADC - center")
        self.axes[1].set_title(f"Filtered waveform ({BANDPASS_LOW_HZ:.0f}-{BANDPASS_HIGH_HZ:.0f} Hz causal IIR)")
        self.axes[1].set_ylabel("float")
        self.axes[2].set_title("Signal level history")
        self.axes[2].set_ylabel("level")
        self.axes[2].set_xlabel("time (s)")
        self.axes[2].legend(loc="upper right")

        for ax in self.axes[:2]:
            ax.set_xlim(-args.window_sec, 0.0)
            ax.grid(True, alpha=0.25)
        self.axes[2].grid(True, alpha=0.25)

        self.prob_bars = None
        if model_labels:
            x = np.arange(len(model_labels))
            self.prob_bars = self.axes[3].bar(x, np.zeros(len(model_labels)), color="#cccccc")
            self.axes[3].set_ylim(0.0, 1.0)
            self.axes[3].set_ylabel("probability")
            self.axes[3].set_xticks(x)
            self.axes[3].set_xticklabels([short_label(label) for label in model_labels], rotation=0)
            self.axes[3].grid(True, axis="y", alpha=0.25)

        self.status_text = self.fig.suptitle("", fontsize=10)
        self.fig.subplots_adjust(left=0.08, right=0.98, bottom=0.08, top=0.90, hspace=0.55)
        self.fig.canvas.manager.set_window_title("STM32 Realtime Audio Monitor")
        self.fig.show()

    # 함수 설명: 'is_open' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def is_open(self) -> bool:
        """현재 값이나 실행 환경이 조건을 만족하는지 boolean으로 판정합니다."""
        return plt.fignum_exists(self.fig.number)

    # 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
    def update(
        self,
        rolling: RollingSignalBuffer,
        stats: MonitorStats,
        pred: PredictionState,
        current_rms: float,
        current_p2p_adc: float,
    ) -> None:
        """RealtimeSignalPlotter.update는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        elapsed = max(0.0, rolling.total_samples / SAMPLE_RATE)
        time_axis, raw_view, filtered_view = rolling.display_view(self.args.max_plot_points)
        self.raw_line.set_data(time_axis, raw_view)
        self.filtered_line.set_data(time_axis, filtered_view)

        now = time.monotonic()
        if now - self.last_ylim_update >= self.args.ylim_interval:
            set_symmetric_ylim(self.axes[0], raw_view, minimum=50.0)
            set_symmetric_ylim(self.axes[1], filtered_view, minimum=0.01)
            self.last_ylim_update = now

        self.level_times.append(elapsed)
        self.level_rms.append(current_rms)
        self.level_p2p_norm.append(current_p2p_adc / 4096.0)
        self.level_snr_norm.append(float(np.clip((pred.snr_total_db or 0.0) / 30.0, 0.0, 1.0)))
        self.level_sub_energy.append(float(max(pred.spectral_subtracted_energy, 0.0)))

        if self.level_times:
            t = np.asarray(self.level_times, dtype=np.float32)
            t_rel = t - t[-1]
            self.rms_line.set_data(t_rel, np.asarray(self.level_rms, dtype=np.float32))
            self.p2p_line.set_data(t_rel, np.asarray(self.level_p2p_norm, dtype=np.float32))
            self.snr_line.set_data(t_rel, np.asarray(self.level_snr_norm, dtype=np.float32))
            sub_energy = np.asarray(self.level_sub_energy, dtype=np.float32)
            sub_energy_norm = sub_energy / max(float(np.max(sub_energy)), 1.0e-12)
            self.sub_energy_line.set_data(t_rel, sub_energy_norm)
            self.axes[2].set_xlim(-self.args.window_sec, 0.0)
            ymax = max(0.01, max(self.level_rms), max(self.level_p2p_norm), max(self.level_snr_norm), float(np.max(sub_energy_norm))) * 1.25
            self.axes[2].set_ylim(0.0, ymax)

        title = (
            f"t={elapsed:.1f}s  packets/s={stats.packets_per_sec:.1f}  "
            f"dropped={stats.dropped_packets}  inserted_samples={stats.inserted_samples}"
        )
        if pred.pred_label:
            snr_text = f"  snr={pred.snr_total_db:.1f}dB" if pred.snr_total_db is not None else ""
            title += (
                f"  |  pred={display_label(pred.pred_label, korean=self.args.korean_font)} {pred.confidence:.3f}  "
                f"vote={display_label(pred.voted_label, korean=self.args.korean_font)} {pred.vote_ratio * 100:.1f}%"
                f"{snr_text}"
            )
        self.status_text.set_text(title)

        if self.model_labels and self.prob_bars is not None:
            probabilities = pred.probabilities or {}
            for label, bar in zip(self.model_labels, self.prob_bars):
                prob = float(probabilities.get(label, 0.0))
                bar.set_height(prob)
                bar.set_color(LABEL_COLORS.get(label, "#cccccc") if label == pred.pred_label else "#cccccc")
            if pred.pred_label:
                self.axes[3].set_title(
                    f"Model probabilities | frame={pred.frame_index} | confidence={pred.confidence:.3f}"
                )
            else:
                self.axes[3].set_title("Model probabilities")

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()


# 클래스 설명: 'TkSignalPlotter' 동작에 필요한 상태와 메서드를 묶는 클래스입니다.
class TkSignalPlotter:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    """TkSignalPlotter는 이 모듈에서 관련 데이터와 동작을 묶어 관리하는 구성 요소입니다."""
    def __init__(self, args: argparse.Namespace, model_labels: list[str]) -> None:
        """TkSignalPlotter 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
        import tkinter as tk

        self.tk = tk
        self.args = args
        self.model_labels = model_labels
        self.closed = False
        self.raw_span = 50.0
        self.filtered_span = 0.01
        self.last_ylim_update = 0.0
        self.level_times: deque[float] = deque(maxlen=600)
        self.level_rms: deque[float] = deque(maxlen=600)
        self.level_p2p_norm: deque[float] = deque(maxlen=600)
        self.level_snr_norm: deque[float] = deque(maxlen=600)
        self.level_sub_energy: deque[float] = deque(maxlen=600)

        self.root = tk.Tk()
        self.root.title("STM32 Realtime Audio Monitor")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.canvas = tk.Canvas(
            self.root,
            width=args.canvas_width,
            height=args.canvas_height,
            bg="white",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.root.update()

    # 함수 설명: 'close' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def close(self) -> None:
        """열어 둔 파일, 오디오 장치, 스레드 등 외부 자원을 정리합니다."""
        self.closed = True
        try:
            self.root.destroy()
        except Exception:
            pass

    # 함수 설명: 'is_open' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def is_open(self) -> bool:
        """현재 값이나 실행 환경이 조건을 만족하는지 boolean으로 판정합니다."""
        if self.closed:
            return False
        try:
            return bool(self.root.winfo_exists())
        except Exception:
            return False

    # 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
    def update(
        self,
        rolling: RollingSignalBuffer,
        stats: MonitorStats,
        pred: PredictionState,
        current_rms: float,
        current_p2p_adc: float,
    ) -> None:
        """TkSignalPlotter.update는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        if not self.is_open():
            return

        elapsed = max(0.0, rolling.total_samples / SAMPLE_RATE)
        time_axis, raw_view, filtered_view = rolling.display_view(self.args.max_plot_points)

        now = time.monotonic()
        if now - self.last_ylim_update >= self.args.ylim_interval:
            self.raw_span = signal_span(raw_view, minimum=50.0)
            self.filtered_span = signal_span(filtered_view, minimum=0.01)
            self.last_ylim_update = now

        self.level_times.append(elapsed)
        self.level_rms.append(current_rms)
        self.level_p2p_norm.append(current_p2p_adc / 4096.0)
        self.level_snr_norm.append(float(np.clip((pred.snr_total_db or 0.0) / 30.0, 0.0, 1.0)))
        self.level_sub_energy.append(float(max(pred.spectral_subtracted_energy, 0.0)))

        canvas = self.canvas
        canvas.delete("dyn")
        width = max(640, int(canvas.winfo_width()))
        height = max(480, int(canvas.winfo_height()))
        left = 64
        right = 18
        top = 44
        bottom = 28
        gap = 22
        row_count = 4 if self.model_labels else 3
        panel_w = width - left - right
        panel_h = max(80, int((height - top - bottom - gap * (row_count - 1)) / row_count))

        title = (
            f"t={elapsed:.1f}s  packets/s={stats.packets_per_sec:.1f}  "
            f"dropped={stats.dropped_packets}  inserted={stats.inserted_samples}"
        )
        if pred.pred_label:
            snr_text = f"  snr={pred.snr_total_db:.1f}dB" if pred.snr_total_db is not None else ""
            title += (
                f"  |  pred={display_label(pred.pred_label, korean=self.args.korean_font)} {pred.confidence:.3f}  "
                f"vote={display_label(pred.voted_label, korean=self.args.korean_font)} {pred.vote_ratio * 100:.1f}%"
                f"{snr_text}"
            )
        canvas.create_text(left, 18, text=title, anchor="w", fill="#111111", tags="dyn")

        y = top
        self.draw_wave_panel(
            left,
            y,
            panel_w,
            panel_h,
            time_axis,
            raw_view,
            self.raw_span,
            "Raw waveform",
            "sample",
            "#1f77b4",
        )

        y += panel_h + gap
        self.draw_wave_panel(
            left,
            y,
            panel_w,
            panel_h,
            time_axis,
            filtered_view,
            self.filtered_span,
            f"Filtered waveform ({BANDPASS_LOW_HZ:.0f}-{BANDPASS_HIGH_HZ:.0f} Hz)",
            "float",
            "#2ca02c",
        )

        y += panel_h + gap
        self.draw_level_panel(left, y, panel_w, panel_h)

        if self.model_labels:
            y += panel_h + gap
            self.draw_probability_panel(left, y, panel_w, panel_h, pred)

        try:
            self.root.update_idletasks()
            self.root.update()
        except self.tk.TclError:
            self.closed = True

    # 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
    def draw_panel_frame(self, x: int, y: int, w: int, h: int, title: str, ylabel: str) -> None:
        """Tk 캔버스에 실시간 모니터링 패널이나 파형 요소를 그립니다."""
        c = self.canvas
        c.create_rectangle(x, y, x + w, y + h, outline="#dddddd", fill="#fbfbfb", tags="dyn")
        c.create_text(x + 8, y + 12, text=title, anchor="w", fill="#333333", tags="dyn")
        c.create_text(x - 10, y + h / 2, text=ylabel, anchor="e", fill="#555555", tags="dyn")
        for frac in (0.25, 0.5, 0.75):
            yy = y + h * frac
            c.create_line(x, yy, x + w, yy, fill="#eeeeee", tags="dyn")

    # 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
    def draw_wave_panel(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        time_axis: np.ndarray,
        values: np.ndarray,
        span: float,
        title: str,
        ylabel: str,
        color: str,
    ) -> None:
        """Tk 캔버스에 실시간 모니터링 패널이나 파형 요소를 그립니다."""
        self.draw_panel_frame(x, y, w, h, title, ylabel)
        if values.size < 2:
            return

        xs = x + ((time_axis - time_axis[0]) / max(1e-6, time_axis[-1] - time_axis[0])) * w
        clipped = np.clip(values, -span, span)
        ys = y + h * 0.5 - (clipped / span) * (h * 0.42)
        coords = np.empty(xs.size * 2, dtype=np.float32)
        coords[0::2] = xs
        coords[1::2] = ys
        self.canvas.create_line(*coords.tolist(), fill=color, width=1, tags="dyn")
        self.canvas.create_text(x + w - 6, y + 12, text=f"±{span:.4g}", anchor="e", fill="#666666", tags="dyn")

    # 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
    def draw_level_panel(self, x: int, y: int, w: int, h: int) -> None:
        """Tk 캔버스에 실시간 모니터링 패널이나 파형 요소를 그립니다."""
        self.draw_panel_frame(x, y, w, h, "Signal level history", "level")
        if len(self.level_times) < 2:
            return

        t = np.asarray(self.level_times, dtype=np.float32)
        t_rel = t - t[-1]
        mask = t_rel >= -self.args.window_sec
        t_rel = t_rel[mask]
        rms = np.asarray(self.level_rms, dtype=np.float32)[mask]
        p2p = np.asarray(self.level_p2p_norm, dtype=np.float32)[mask]
        snr = np.asarray(self.level_snr_norm, dtype=np.float32)[mask]
        sub_energy = np.asarray(self.level_sub_energy, dtype=np.float32)[mask]
        sub_energy_norm = sub_energy / max(float(np.max(sub_energy)), 1.0e-12)
        ymax = max(0.01, float(np.max(rms)), float(np.max(p2p)), float(np.max(snr)), float(np.max(sub_energy_norm))) * 1.25

        self.draw_level_line(x, y, w, h, t_rel, rms, ymax, "#d62728")
        self.draw_level_line(x, y, w, h, t_rel, p2p, ymax, "#9467bd")
        self.draw_level_line(x, y, w, h, t_rel, snr, ymax, "#ff7f0e")
        self.draw_level_line(x, y, w, h, t_rel, sub_energy_norm, ymax, "#17becf")
        self.canvas.create_text(
            x + w - 8,
            y + 14,
            text="red=RMS  purple=p2p  orange=SNR/30dB  cyan=sub-energy",
            anchor="e",
            fill="#555555",
            tags="dyn",
        )

    # 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
    def draw_level_line(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        t_rel: np.ndarray,
        values: np.ndarray,
        ymax: float,
        color: str,
    ) -> None:
        """Tk 캔버스에 실시간 모니터링 패널이나 파형 요소를 그립니다."""
        if values.size < 2:
            return
        xs = x + ((t_rel + self.args.window_sec) / self.args.window_sec) * w
        ys = y + h - np.clip(values / ymax, 0.0, 1.0) * (h * 0.82) - h * 0.08
        coords = np.empty(xs.size * 2, dtype=np.float32)
        coords[0::2] = xs
        coords[1::2] = ys
        self.canvas.create_line(*coords.tolist(), fill=color, width=2, tags="dyn")

    # 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
    def draw_probability_panel(self, x: int, y: int, w: int, h: int, pred: PredictionState) -> None:
        """Tk 캔버스에 실시간 모니터링 패널이나 파형 요소를 그립니다."""
        self.draw_panel_frame(x, y, w, h, "Model probabilities", "prob")
        probabilities = pred.probabilities or {}
        n = max(1, len(self.model_labels))
        gap = 10
        bar_w = max(18, (w - gap * (n + 1)) / n)

        for i, label in enumerate(self.model_labels):
            prob = float(probabilities.get(label, 0.0))
            x0 = x + gap + i * (bar_w + gap)
            x1 = x0 + bar_w
            y1 = y + h - 24
            y0 = y1 - np.clip(prob, 0.0, 1.0) * (h - 52)
            color = LABEL_COLORS.get(label, "#999999") if label == pred.pred_label else "#cccccc"
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="", tags="dyn")
            self.canvas.create_text((x0 + x1) / 2, y1 + 10, text=LABEL_ICONS.get(label, label), fill="#333333", tags="dyn")
            self.canvas.create_text((x0 + x1) / 2, y0 - 8, text=f"{prob:.2f}", fill="#333333", tags="dyn")


# 함수 설명: 'set_symmetric_ylim' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def set_symmetric_ylim(ax, values: np.ndarray, minimum: float) -> None:
    """set_symmetric_ylim는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    if values.size == 0:
        span = minimum
    else:
        span = float(np.max(np.abs(values))) * 1.15
        span = max(span, minimum)
    ax.set_ylim(-span, span)


# 함수 설명: 'signal_span' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def signal_span(values: np.ndarray, minimum: float) -> float:
    """signal_span는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    if values.size == 0:
        return minimum
    return max(float(np.max(np.abs(values))) * 1.15, minimum)


# 함수 설명: 'short_label' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def short_label(label: str) -> str:
    """내부 상태값을 콘솔이나 그래프에 표시하기 좋은 문자열 또는 라벨로 변환합니다."""
    return LABEL_ICONS.get(label, "") + "\n" + label


# 함수 설명: 'display_label' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def display_label(label: str, korean: bool = True) -> str:
    """내부 상태값을 콘솔이나 그래프에 표시하기 좋은 문자열 또는 라벨로 변환합니다."""
    if not label:
        return ""
    name = LABEL_NAMES.get(label, label) if korean else label
    return f"{LABEL_ICONS.get(label, '')} {name}".strip()


# 함수 설명: 'adc_to_float' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def adc_to_float(adc: np.ndarray, adc_center: int, pcm_gain: float) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    centered = adc.astype(np.float32) - float(adc_center)
    return np.clip(centered * float(pcm_gain) / 32768.0, -1.0, 1.0).astype(np.float32)


# 함수 설명: 'adc_to_pcm_i16' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def adc_to_pcm_i16(adc: np.ndarray, adc_center: int, pcm_gain: float) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    centered = adc.astype(np.float32) - float(adc_center)
    pcm = np.clip(centered * float(pcm_gain), -32768, 32767)
    return pcm.astype("<i2")


def resolve_packet_sample_format(packet: AudioPacket, requested: str) -> int:
    """내부 상태값을 콘솔이나 그래프에 표시하기 좋은 문자열 또는 라벨로 변환합니다."""
    if requested == "pcm16":
        return AUDIO_FORMAT_PCM16
    if requested == "adc_u16":
        return AUDIO_FORMAT_ADC_U16
    return packet.sample_format


def apply_pcm16_gain_float(pcm: np.ndarray, gain: float) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    audio = pcm.astype(np.float32) * float(gain) / 32768.0
    return np.clip(audio, -1.0, 1.0)


def apply_pcm16_gain_i16(pcm: np.ndarray, gain: float) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    if float(gain) == 1.0:
        return pcm.astype("<i2", copy=True)
    scaled = np.rint(pcm.astype(np.float32) * float(gain))
    scaled = np.clip(scaled, -32768, 32767)
    return scaled.astype("<i2")


def packet_to_float(packet: AudioPacket, requested: str, adc_center: int, pcm_gain: float, pcm16_gain: float) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    sample_format = resolve_packet_sample_format(packet, requested)
    if sample_format == AUDIO_FORMAT_PCM16:
        return apply_pcm16_gain_float(packet.adc.view("<i2"), pcm16_gain)
    return adc_to_float(packet.adc, adc_center, pcm_gain)


def packet_to_pcm_i16(packet: AudioPacket, requested: str, adc_center: int, pcm_gain: float, pcm16_gain: float) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    sample_format = resolve_packet_sample_format(packet, requested)
    if sample_format == AUDIO_FORMAT_PCM16:
        return apply_pcm16_gain_i16(packet.adc.view("<i2"), pcm16_gain)
    return adc_to_pcm_i16(packet.adc, adc_center, pcm_gain)


def packet_to_centered_debug(packet: AudioPacket, requested: str, adc_center: int) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    sample_format = resolve_packet_sample_format(packet, requested)
    if sample_format == AUDIO_FORMAT_PCM16:
        return packet.adc.view("<i2").astype(np.float32)
    return packet.adc.astype(np.float32) - float(adc_center)


# 함수 설명: 'ensure_scipy_signal' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def ensure_scipy_signal():
    """ensure_scipy_signal는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    global signal
    if signal is None:
        try:
            from scipy import signal as scipy_signal
        except ImportError as exc:
            raise DependencyError("scipy is required. Install it with: pip install scipy") from exc
        signal = scipy_signal
    return signal


# 함수 설명: 'design_bandpass' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def design_bandpass(sample_rate: int) -> np.ndarray:
    """design_bandpass는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    scipy_signal = ensure_scipy_signal()
    nyquist = sample_rate * 0.5
    return scipy_signal.butter(
        BANDPASS_ORDER,
        [BANDPASS_LOW_HZ / nyquist, BANDPASS_HIGH_HZ / nyquist],
        btype="bandpass",
        output="sos",
    )


# 함수 설명: 'seq_gap' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def seq_gap(expected_seq: int, actual_seq: int) -> int:
    """seq_gap는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    return (actual_seq - expected_seq) % UINT32_MOD


# 함수 설명: 'estimate_missing_samples' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def estimate_missing_samples(
    first_missing_seq: int,
    missing_packets: int,
    packet_samples: int,
    packets_per_half: int,
    short_packet_samples: int,
    short_packet_mod: int | None,
) -> int:
    """패킷 seq 차이를 기반으로 누락된 샘플 수나 상태를 추정합니다."""
    if missing_packets <= 0:
        return 0

    if short_packet_mod is None:
        return missing_packets * packet_samples

    total = 0
    for i in range(missing_packets):
        seq = (first_missing_seq + i) % UINT32_MOD
        if seq % packets_per_half == short_packet_mod:
            total += short_packet_samples
        else:
            total += packet_samples
    return total


# 함수 설명: 파일, 시리얼, 모델, 설정 등 외부 입력을 읽어 메모리에 올립니다.
def load_realtime_validate_module():
    """외부 파일이나 선택 모듈을 읽어 현재 실행에서 사용할 객체로 준비합니다."""
    module_path = Path(__file__).resolve().parents[1] / "collection" / "realtime_validate.py"
    spec = importlib.util.spec_from_file_location("realtime_validate_for_monitor", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load realtime_validate.py from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
def update_packet_rate(stats: MonitorStats, now: float, interval_sec: float = 1.0) -> None:
    """새로 들어온 데이터에 맞춰 상태, 통계, 그래프 표시를 갱신합니다."""
    elapsed = now - stats.last_status_time
    if elapsed < interval_sec:
        return

    packet_delta = stats.total_packets - stats.last_status_packets
    stats.packets_per_sec = packet_delta / max(elapsed, 1e-6)
    stats.last_status_time = now
    stats.last_status_packets = stats.total_packets


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def print_status(
    stats: MonitorStats,
    pred: PredictionState,
    current_rms: float,
    current_p2p_adc: float,
) -> None:
    """현재 처리 상태를 사용자가 확인하기 쉬운 콘솔 메시지로 출력합니다."""
    msg = (
        f"pps={stats.packets_per_sec:5.1f} "
        f"dropped={stats.dropped_packets} "
        f"rms={current_rms:.5f} "
        f"adc_p2p={current_p2p_adc:6.1f}"
    )
    if pred.pred_label:
        snr_text = f" snr={pred.snr_total_db:.1f}dB" if pred.snr_total_db is not None else ""
        msg += (
            f" pred={display_label(pred.pred_label)} conf={pred.confidence:.3f} "
            f"vote={display_label(pred.voted_label)}"
            f"{snr_text}"
        )
    print(msg)


# 함수 설명: 선택된 작업 흐름을 순서대로 실행하고 하위 단계를 호출합니다.
def run_monitor(args: argparse.Namespace) -> None:
    """사용자가 선택한 모드의 실제 수집, 테스트, 모니터링 루프를 실행합니다."""
    if serial is None:
        raise DependencyError("pyserial is required. Install it with: pip install pyserial")

    model_labels: list[str] = []
    rolling = RollingSignalBuffer(SAMPLE_RATE, args.window_sec)
    plotter = TkSignalPlotter(args, model_labels) if args.plot_backend == "tk" else RealtimeSignalPlotter(args, model_labels)

    sos = design_bandpass(SAMPLE_RATE)
    scipy_signal = ensure_scipy_signal()
    zi = scipy_signal.sosfilt_zi(sos) * 0.0
    packets_per_half = (args.half_buffer_samples + args.packet_samples - 1) // args.packet_samples
    short_packet_samples = args.half_buffer_samples - args.packet_samples * (packets_per_half - 1)
    if short_packet_samples <= 0:
        short_packet_samples = args.packet_samples

    stats = MonitorStats(start_time=time.monotonic(), last_status_time=time.monotonic())
    pred = PredictionState(probabilities={label: 0.0 for label in model_labels})

    writer = WavPcmWriter(Path(args.save_wav), SAMPLE_RATE) if args.save_wav else None
    player = AudioPlayer(SAMPLE_RATE) if args.play_audio else None
    if player is not None:
        player.start()
    ser = serial.Serial(args.port, args.baudrate, timeout=args.serial_timeout)
    send_board_ai_inference_command(ser, args.ai_inference)
    receiver = PacketReceiver(ser, max_packet_samples=args.max_packet_samples)

    current_rms = 0.0
    current_p2p_adc = 0.0
    last_plot_time = 0.0
    last_print_time = 0.0

    try:
        time.sleep(args.open_delay)
        ser.reset_input_buffer()
        print("STM32 packet sync 대기 중...")
        if args.save_wav:
            print(f"save_wav: {args.save_wav}")
        print("그래프 창을 닫거나 Ctrl+C를 누르면 종료됩니다.")

        while plotter.is_open():
            packet = receiver.read_packet()

            if packet.samples != args.packet_samples:
                stats.short_packet_mod = packet.seq % packets_per_half

            if stats.expected_seq is not None and packet.seq != stats.expected_seq:
                gap = seq_gap(stats.expected_seq, packet.seq)
                if 0 < gap <= args.max_fill_gap_packets:
                    missing_samples = estimate_missing_samples(
                        first_missing_seq=stats.expected_seq,
                        missing_packets=gap,
                        packet_samples=args.packet_samples,
                        packets_per_half=packets_per_half,
                        short_packet_samples=short_packet_samples,
                        short_packet_mod=stats.short_packet_mod,
                    )
                    zero_raw = np.zeros(missing_samples, dtype=np.float32)
                    zero_audio = np.zeros(missing_samples, dtype=np.float32)
                    zero_filtered, zi = scipy_signal.sosfilt(sos, zero_audio, zi=zi)
                    rolling.append(zero_raw, zero_filtered.astype(np.float32))
                    stats.dropped_packets += gap
                    stats.inserted_samples += missing_samples
                    silence_pcm = np.zeros(missing_samples, dtype="<i2")
                    if writer is not None:
                        writer.write(silence_pcm)
                    if player is not None:
                        player.push(silence_pcm)
                    print(
                        f"[WARN] seq jump: expected={stats.expected_seq}, "
                        f"got={packet.seq}, missing={gap}, inserted_samples={missing_samples}"
                    )
                else:
                    print(f"[WARN] seq resync/reset: expected={stats.expected_seq}, got={packet.seq}, gap={gap}")

            stats.expected_seq = (packet.seq + 1) % UINT32_MOD
            stats.total_packets += 1
            stats.received_samples += packet.samples

            raw_centered = packet_to_centered_debug(packet, args.sample_format, args.adc_center)
            audio = packet_to_float(packet, args.sample_format, args.adc_center, args.pcm_gain, args.pcm16_gain)
            filtered, zi = scipy_signal.sosfilt(sos, audio, zi=zi)
            filtered = filtered.astype(np.float32)
            rolling.append(raw_centered, filtered)

            current_rms = float(np.sqrt(np.mean(filtered * filtered))) if filtered.size else 0.0
            current_p2p_adc = float(np.max(raw_centered) - np.min(raw_centered)) if raw_centered.size else 0.0

            if writer is not None or player is not None:
                pcm = packet_to_pcm_i16(packet, args.sample_format, args.adc_center, args.pcm_gain, args.pcm16_gain)
                if writer is not None:
                    writer.write(pcm)
                if player is not None:
                    player.push(pcm)

            now = time.monotonic()
            update_packet_rate(stats, now)

            if now - last_plot_time >= args.update_interval:
                plotter.update(rolling, stats, pred, current_rms, current_p2p_adc)
                last_plot_time = now

            if now - last_print_time >= args.print_interval:
                print_status(stats, pred, current_rms, current_p2p_adc)
                last_print_time = now

            if args.duration_sec and rolling.total_samples >= int(args.duration_sec * SAMPLE_RATE):
                break

    except KeyboardInterrupt:
        print("\n[STOP] 사용자 중단")
    finally:
        ser.close()
        if writer is not None:
            writer.close()
            print(f"saved wav: {writer.path}")
        if player is not None:
            player.close()


# 함수 설명: 명령행 옵션을 정의하고 사용자가 입력한 인자를 파싱합니다.
def parse_args(argv: list[str]) -> argparse.Namespace:
    """명령행에서 받을 옵션과 기본값을 정의하고 argparse 객체로 반환합니다."""
    parser = argparse.ArgumentParser(description="Realtime waveform monitor for STM32 USB CDC audio stream.")
    parser.add_argument("port", help="STM32 USB CDC COM port, e.g. COM5")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--adc-center", type=int, default=DEFAULT_ADC_CENTER)
    parser.add_argument("--pcm-gain", type=float, default=DEFAULT_PCM_GAIN)
    parser.add_argument("--pcm16-gain", type=float, default=1.0, help="digital gain applied only to pcm16/I2S samples")
    parser.add_argument(
        "--sample-format",
        choices=SAMPLE_FORMAT_CHOICES,
        default="auto",
        help="audio payload format: auto uses packet reserved field, adc_u16 is MAX9814 ADC, pcm16 is I2S PCM",
    )
    parser.add_argument("--packet-samples", type=int, default=DEFAULT_PACKET_SAMPLES)
    parser.add_argument("--half-buffer-samples", type=int, default=DEFAULT_HALF_BUFFER_SAMPLES)
    parser.add_argument("--max-packet-samples", type=int, default=4096)
    parser.add_argument("--max-fill-gap-packets", type=int, default=1000)
    parser.add_argument("--serial-timeout", type=float, default=0.05)
    parser.add_argument("--open-delay", type=float, default=2.0)
    parser.add_argument(
        "--ai-inference",
        choices=("off", "on", "keep"),
        default="off",
        help="send AI OFF/ON to the board after opening COM; default off for clean raw waveform/audio checks",
    )
    parser.add_argument(
        "--plot-backend",
        choices=("tk", "matplotlib"),
        default="tk",
        help="tk is faster and starts quickly; matplotlib is prettier but slower",
    )
    parser.add_argument("--canvas-width", type=int, default=1100, help="tk backend window width")
    parser.add_argument("--canvas-height", type=int, default=760, help="tk backend window height")
    parser.add_argument("--window-sec", type=float, default=3.0, help="seconds visible in the rolling waveform")
    parser.add_argument("--update-interval", type=float, default=0.12, help="plot refresh interval in seconds")
    parser.add_argument("--max-plot-points", type=int, default=2000, help="maximum points drawn per waveform line")
    parser.add_argument("--ylim-interval", type=float, default=0.5, help="seconds between automatic y-axis rescale updates")
    parser.add_argument("--korean-font", action="store_true", help="enable Korean font lookup for plot labels; slower startup")
    parser.add_argument("--print-interval", type=float, default=1.0, help="console status interval in seconds")
    parser.add_argument("--duration-sec", type=float, default=0.0, help="optional auto-stop duration")
    parser.add_argument("--save-wav", help="optional mono 16-bit PCM WAV output path")
    parser.add_argument("--play-audio", action="store_true", help="play received PCM audio in real time via sounddevice")
    args = parser.parse_args(argv)
    return args


# 함수 설명: 스크립트 진입점으로 인자를 읽고 전체 실행 흐름을 호출합니다.
def main(argv: list[str] | None = None) -> int:
    """스크립트 진입점으로 CLI 인자를 읽고 전체 실행 흐름을 순서대로 호출합니다."""
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
