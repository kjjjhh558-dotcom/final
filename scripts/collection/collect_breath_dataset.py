# -*- coding: utf-8 -*-
"""STM32 USB CDC 오디오 스트림을 받아 호흡 데이터셋 WAV와 metadata.csv를 생성합니다.

처음 넘겨받는 사람은 이 파일에서 수집 프로토콜, 실시간 청취, 패킷 누락 감지, train/test 분할, 세션 폴더 생성 흐름을 확인하면 됩니다. 보드가 보내는 0xAABBCCDD 오디오 패킷을 읽고, 선택한 호흡 동작 순서대로 WAV 클립과 메타데이터를 남깁니다."""

# 파일 설명: STM32 USB CDC 오디오를 수집해 통합 dataset WAV와 metadata만 만듭니다.
#
# collect_breath_dataset.py
#
# 목적:
#   STM32F407 + MAX9814에서 USB CDC로 전송되는 binary 오디오 패킷을 받아
#   호흡 분류 학습용 WAV 클립 데이터셋을 생성하는 CLI 프로그램입니다.
#
# 실행하면 일어나는 일:
#   1. 지정한 COM 포트를 엽니다.
#   2. MAGIC 값(0xAABBCCDD)으로 STM32 오디오 패킷 경계를 동기화합니다.
#   3. seq 번호로 패킷 누락을 감지합니다.
#   4. 누락된 패킷은 무음으로 채워 전체 시간축을 유지합니다.
#   5. ADC 샘플을 16-bit PCM으로 변환합니다.
#        centered = adc - adc_center
#        pcm      = centered * pcm_gain
#   6. dataset/<label>/<label>_NNN.wav 구조로 클래스별 WAV 파일을 저장합니다.
#   7. dataset/metadata.csv에 수집 정보를 누적합니다.
#   8. 옵션을 켜면 dataset 루트에 전체 세션 WAV도 함께 저장합니다.
#
# 이어서 수집:
#   같은 --out-dir로 다시 실행하면 dataset 전체의 기존 번호를 스캔합니다.
#   프로토콜이나 --name이 달라도 클래스별 WAV 파일 번호는 기존 파일 다음부터 이어지고,
#   dataset/metadata.csv도 덮어쓰지 않고 아래에 새 행을 추가합니다.
#
# 수집 프로토콜:
#   --protocol nasal
#     nasal_inhale/gap/nasal_exhale만 반복합니다.
#     기본 repeats 10을 내부적으로 20회로 늘려 데이터 수집량을 2배로 확보합니다.
#     gap은 기본 pause의 절반 길이이며 WAV로 저장하지 않습니다.
#   --protocol mouth
#     mouth_inhale/gap/mouth_exhale만 반복합니다.
#     기본 repeats 10을 내부적으로 20회로 늘려 데이터 수집량을 2배로 확보합니다.
#     gap은 기본 pause의 절반 길이이며 WAV로 저장하지 않습니다.
#   --protocol noise
#     noise 구간만 반복 저장합니다. 기본은 5초 noise를 repeats 횟수만큼 저장합니다.
#
# 저장 규칙:
#   - 호흡 구간은 앞 0.25초와 뒤 0.25초를 버리고 usable 구간만 저장합니다.
#     예: 2.5초 호흡 수집 -> 2.0초 WAV 저장
#   - nasal/mouth 단독 프로토콜의 gap 구간은 저장하지 않습니다.
#   - noise 구간은 --protocol noise에서만 저장합니다.
#
# 출력 구조:
#   dataset/
#     nasal_inhale/
#     nasal_exhale/
#     mouth_inhale/
#     mouth_exhale/
#     noise/
#     metadata.csv
#
# split 규칙:
#   수집 단계에서는 train/test 폴더를 만들지 않습니다.
#   feature 추출 단계에서 파일 번호 기준으로 5번째마다 test, 나머지를 train으로 판단합니다.
#   예: nasal_inhale_005.wav -> test, nasal_inhale_006.wav -> train
#
# 사용 방법:
#   1. 필요한 패키지 설치:
#        pip install pyserial numpy
#   2. STM32 보드 연결 후 장치 관리자에서 COM 포트를 확인합니다.
#   3. 기본 실행:
#        python collect_breath_dataset.py COM5 --out-dir dataset --name nasal_session
#      같은 --out-dir로 다시 실행하면 dataset 전체 기준으로 번호를 이어서 저장합니다.
#   4. 5회 빠른 테스트 수집:
#        python collect_breath_dataset.py COM5 --out-dir dataset --name nasal_quick --quick-5
#      - nasal/mouth 프로토콜 기준 실제 10회 inhale/exhale pair 수집
#      - 호흡 클래스별 usable 약 20초
#   5. 코 들숨/날숨만 수집:
#        python collect_breath_dataset.py COM5 --out-dir dataset --name nasal_session --protocol nasal
#   6. 입 들숨/날숨만 수집:
#        python collect_breath_dataset.py COM5 --out-dir dataset --name mouth_session --protocol mouth
#   7. 노이즈만 수집:
#        python collect_breath_dataset.py COM5 --out-dir dataset --name noise_session --protocol noise
#      노이즈 클립 길이를 바꾸려면 --noise-sec를 사용합니다.
#   8. 15회 반복 수집:
#        python collect_breath_dataset.py COM5 --out-dir dataset --name nasal_session --protocol nasal --repeats 15
#   9. 전체 세션 WAV도 함께 저장:
#        python collect_breath_dataset.py COM5 --save-session-wav
#   10. ADC offset 또는 PCM gain 조정:
#        python collect_breath_dataset.py COM5 --adc-center 1551 --pcm-gain 16
#   11. 수집 중 현재 STEP 재녹음:
#        기본값은 p 키입니다. 수집 중 p를 누르면 현재 STEP에서 생성 중이거나 이미 생성된
#        WAV/metadata row를 삭제하고 Enter 입력 후 같은 STEP부터 다시 녹음합니다.
#   12. 종료:
#        기본 nasal/mouth 10회 반복은 약 120초 후 자동 종료됩니다.
#        --quick-5는 약 60초 후 자동 종료됩니다.
#        중간에 멈추려면 Ctrl + C를 누릅니다.

from __future__ import annotations

import argparse
import ctypes
import csv
from dataclasses import dataclass
from datetime import datetime
import os
import queue
import struct
import sys
import threading
import time
import wave

try:
    import msvcrt
except ImportError:
    msvcrt = None

import numpy as np

try:
    import serial

    SerialException = serial.SerialException
except ImportError:
    serial = None

    # 클래스 설명: 'SerialException' 예외 상황을 표현하는 전용 오류 타입입니다.
    class SerialException(Exception):
        pass


# 클래스 설명: 'DependencyError' 예외 상황을 표현하는 전용 오류 타입입니다.
class DependencyError(RuntimeError):
    """DependencyError는 선택 의존성이 없을 때 사용자에게 설치 안내를 주기 위한 전용 예외입니다."""
    pass


MAGIC = 0xAABBCCDD
HEADER_SIZE = 12
UINT32_MOD = 0x100000000
AUDIO_FORMAT_ADC_U16 = 0
AUDIO_FORMAT_PCM16 = 1
SAMPLE_FORMAT_CHOICES = ("auto", "adc_u16", "pcm16")

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_ADC_CENTER = 1551
DEFAULT_PCM_GAIN = 16.0
DEFAULT_PCM16_GAIN = 1.0
DEFAULT_PACKET_SAMPLES = 512
DEFAULT_HALF_BUFFER_SAMPLES = 4000

DEFAULT_BREATH_SEC = 2.5
DEFAULT_PAUSE_SEC = 1.0
DEFAULT_EDGE_TRIM_SEC = 0.25
DEFAULT_REPEATS = 10
SINGLE_CLASS_PROTOCOL_REPEAT_MULTIPLIER = 2
QUICK_REPEATS = 5
DEFAULT_PROTOCOL = "nasal"
DEFAULT_NOISE_SEC = 5.0
PROTOCOL_CHOICES = ("nasal", "mouth", "noise")
SPLITS = ("train", "test")
TRAIN_RATIO = 0.8
TEST_EVERY_N = 5

DATASET_LABELS = (
    "nasal_inhale",
    "nasal_exhale",
    "mouth_inhale",
    "mouth_exhale",
    "noise",
)


# 클래스 설명: 'AudioPacket' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
@dataclass(frozen=True)
class AudioPacket:
    """AudioPacket는 펌웨어나 센서에서 받은 한 개 패킷의 필드를 묶어 전달하는 데이터 구조입니다."""
    seq: int
    samples: int
    adc: np.ndarray
    sample_format: int = AUDIO_FORMAT_ADC_U16


# 클래스 설명: 'ProtocolPhase' 동작에 필요한 상태와 메서드를 묶는 클래스입니다.
@dataclass(frozen=True)
class ProtocolPhase:
    """ProtocolPhase는 이 모듈에서 관련 데이터와 동작을 묶어 관리하는 구성 요소입니다."""
    start_sec: float
    end_sec: float
    label: str
    prompt: str
    repeat: int
    trim_edges: bool = False
    save_clip: bool = True

    # 함수 설명: 'duration_sec' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    @property
    def duration_sec(self) -> float:
        """ProtocolPhase.duration_sec는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        return self.end_sec - self.start_sec


# 클래스 설명: 'ClipSpec' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
@dataclass(frozen=True)
class ClipSpec:
    """ClipSpec는 이 모듈에서 관련 데이터와 동작을 묶어 관리하는 구성 요소입니다."""
    filename: str
    label: str
    split: str
    repeat: int
    start_sample: int
    end_sample: int
    path: str

    # 함수 설명: 'expected_samples' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    @property
    def expected_samples(self) -> int:
        """ClipSpec.expected_samples는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        return self.end_sample - self.start_sample


# 클래스 설명: 'StreamStats' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
@dataclass
class StreamStats:
    """StreamStats는 실시간 처리 중 누적되는 상태값과 통계를 보관합니다."""
    total_packets: int = 0
    dropped_packets: int = 0
    resync_events: int = 0
    inserted_samples: int = 0
    received_samples: int = 0
    written_samples: int = 0
    expected_seq: int | None = None
    short_packet_mod: int | None = None

    window_packets: int = 0
    window_min: int | None = None
    window_max: int | None = None
    window_sum_sq: float = 0.0
    window_samples: int = 0
    last_debug_time: float = 0.0


# 함수 설명: 실행 환경이나 출력 형식을 현재 작업에 맞게 설정합니다.
def configure_utf8_stdio() -> None:
    """실행 환경, 출력 인코딩, 라이브러리 옵션처럼 본 처리 전에 필요한 설정을 적용합니다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def console_hotkeys_available() -> bool:
    """현재 값이나 실행 환경이 조건을 만족하는지 boolean으로 판정합니다."""
    return os.name == "nt" and msvcrt is not None


def poll_console_key() -> str | None:
    """poll_console_key는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    if not console_hotkeys_available():
        return None

    while msvcrt.kbhit():
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            if msvcrt.kbhit():
                msvcrt.getwch()
            continue
        return key

    return None


def clear_console_keys() -> None:
    """clear_console_keys는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    if not console_hotkeys_available():
        return

    while msvcrt.kbhit():
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0") and msvcrt.kbhit():
            msvcrt.getwch()


# 함수 설명: 파일, 시리얼, 모델, 설정 등 외부 입력을 읽어 메모리에 올립니다.
def read_exact(ser: serial.Serial, size: int, timeout_sec: float = 2.0) -> bytes:
    """시리얼 포트에서 지정한 byte 수가 모일 때까지 읽고 timeout 시 오류를 냅니다."""
    data = bytearray()
    deadline = time.monotonic() + timeout_sec

    while len(data) < size:
        chunk = ser.read(size - len(data))
        if chunk:
            data.extend(chunk)
            deadline = time.monotonic() + timeout_sec
            continue

        if time.monotonic() > deadline:
            raise TimeoutError(f"serial timeout while reading {size} bytes")

    return bytes(data)


# 클래스 설명: 'AudioPacketReceiver' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
class AudioPacketReceiver:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    """AudioPacketReceiver는 시리얼 byte stream에서 필요한 packet을 동기화하고 파싱합니다."""
    def __init__(self, ser: serial.Serial, max_packet_samples: int = 4096) -> None:
        """AudioPacketReceiver 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
        self.ser = ser
        self.max_packet_samples = max_packet_samples

    # 함수 설명: 입력 스트림이나 목록에서 필요한 위치와 대상을 찾아 동기화합니다.
    def find_magic(self) -> None:
        """시리얼 stream에서 packet 시작을 나타내는 magic word까지 byte를 버리며 동기화합니다."""
        sync = bytearray()

        while True:
            b = self.ser.read(1)
            if not b:
                continue

            sync += b
            if len(sync) > 4:
                del sync[:-4]

            if len(sync) == 4 and struct.unpack("<I", sync)[0] == MAGIC:
                return

    # 함수 설명: 파일, 시리얼, 모델, 설정 등 외부 입력을 읽어 메모리에 올립니다.
    def read_packet(self) -> AudioPacket:
        """동기화된 시리얼 stream에서 header와 payload를 읽어 packet 객체로 변환합니다."""
        while True:
            self.find_magic()
            rest = read_exact(self.ser, HEADER_SIZE - 4)
            seq, samples, reserved = struct.unpack("<IHH", rest)

            if samples == 0 or samples > self.max_packet_samples:
                print(f"[WARN] invalid samples={samples}; resyncing")
                continue

            payload = read_exact(self.ser, samples * 2)
            adc = np.frombuffer(payload, dtype="<u2")

            if adc.size != samples:
                print(f"[WARN] payload mismatch: expected={samples}, got={adc.size}")
                continue

            sample_format = AUDIO_FORMAT_PCM16 if reserved == AUDIO_FORMAT_PCM16 else AUDIO_FORMAT_ADC_U16
            return AudioPacket(seq=seq, samples=samples, adc=adc, sample_format=sample_format)


# 클래스 설명: 'WavPcmWriter' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
class WavPcmWriter:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    """WavPcmWriter는 수집 또는 모니터링 결과를 파일로 안전하게 기록합니다."""
    def __init__(self, path: str, sample_rate: int) -> None:
        """WavPcmWriter 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
        self.path = path
        self.sample_rate = sample_rate
        self.frames_written = 0
        self._wav = wave.open(path, "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)

    # 함수 설명: 계산된 결과나 데이터를 파일 또는 출력 장치에 저장합니다.
    def write_pcm_i16(self, pcm: np.ndarray) -> None:
        """계산된 결과나 설정 값을 CSV, JSON, WAV, C 헤더 같은 출력 파일로 저장합니다."""
        if pcm.size == 0:
            return
        pcm_i16 = pcm.astype("<i2", copy=False)
        self._wav.writeframes(pcm_i16.tobytes())
        self.frames_written += int(pcm_i16.size)

    # 함수 설명: 'close' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def close(self) -> None:
        """열어 둔 파일, 오디오 장치, 스레드 등 외부 자원을 정리합니다."""
        self._wav.close()


# 클래스 설명: 'SegmentedDatasetWriter' 관련 데이터를 묶고 전달하거나 상태를 관리하는 구조입니다.
class WaveFormatEx(ctypes.Structure):
    """WaveFormatEx는 Windows winmm 오디오 API 호출에 필요한 C 구조체 정의입니다."""
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
    """WaveHdr는 Windows winmm 오디오 API 호출에 필요한 C 구조체 정의입니다."""
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
    """LivePcmPlayer는 수신한 PCM 오디오를 PC에서 실시간 재생하기 위한 보조 구성 요소입니다."""
    CALLBACK_NULL = 0
    WAVE_FORMAT_PCM = 1
    WAVE_MAPPER = ctypes.c_uint(-1).value
    WHDR_DONE = 0x00000001

    def __init__(self, sample_rate: int, queue_sec: float = 0.75, gain: float = 1.0) -> None:
        """LivePcmPlayer 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
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
        max_buffers = max(2, int(round(queue_sec * self.sample_rate / float(DEFAULT_PACKET_SAMPLES))))
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=max_buffers)
        self._winmm = ctypes.WinDLL("winmm")
        self._configure_winmm()
        self._open_device()
        self._thread = threading.Thread(target=self._worker, name="collection-audio-playback", daemon=True)
        self._thread.start()

    def _configure_winmm(self) -> None:
        """LivePcmPlayer._configure_winmm는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
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
        """LivePcmPlayer._raise_if_error는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        if int(code) != 0:
            raise RuntimeError(f"winmm {action} failed with code {code}")

    def _open_device(self) -> None:
        """LivePcmPlayer._open_device는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
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
        """LivePcmPlayer.write는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
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
        """완료된 작업 항목을 정리하고 아직 처리 중인 항목만 남깁니다."""
        active: list[tuple[WaveHdr, ctypes.Array]] = []
        for header, buffer in pending:
            if header.dwFlags & self.WHDR_DONE:
                self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(header), ctypes.sizeof(header))
            else:
                active.append((header, buffer))
        return active

    def _worker(self) -> None:
        """백그라운드 스레드에서 queue를 소비하며 장치 I/O 작업을 처리합니다."""
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
        """열어 둔 파일, 오디오 장치, 스레드 등 외부 자원을 정리합니다."""
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


class SegmentedDatasetWriter:
    # 함수 설명: '__init__' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    """SegmentedDatasetWriter는 수집 또는 모니터링 결과를 파일로 안전하게 기록합니다."""
    def __init__(
        self,
        clips: list[ClipSpec],
        sample_rate: int,
        adc_center: int,
        pcm_gain: float,
        sample_format: str,
        pcm16_gain: float,
        session_name: str,
        protocol: str,
        dataset_dir: str,
    ) -> None:
        """SegmentedDatasetWriter 인스턴스가 사용할 버퍼, 파일 핸들, 장치 상태를 초기화합니다."""
        self.clips = clips
        self.sample_rate = sample_rate
        self.adc_center = adc_center
        self.pcm_gain = pcm_gain
        self.sample_format = sample_format
        self.pcm16_gain = pcm16_gain
        self.session_name = session_name
        self.protocol = protocol
        self.dataset_dir = dataset_dir
        self.current_index = 0
        self.current_writer: WavPcmWriter | None = None
        self.current_written = 0
        self.metadata_rows: list[dict[str, str]] = []
        self.written_clip_paths: list[str] = []

    # 함수 설명: 계산된 결과나 데이터를 파일 또는 출력 장치에 저장합니다.
    def write_block(self, block_start_sample: int, pcm: np.ndarray) -> None:
        """계산된 결과나 설정 값을 CSV, JSON, WAV, C 헤더 같은 출력 파일로 저장합니다."""
        if pcm.size == 0:
            return

        block_end_sample = block_start_sample + int(pcm.size)

        while self.current_index < len(self.clips):
            clip = self.clips[self.current_index]

            if block_end_sample <= clip.start_sample:
                break

            if block_start_sample >= clip.end_sample:
                self._finalize_open_clip(complete=False)
                self.current_index += 1
                continue

            overlap_start = max(block_start_sample, clip.start_sample)
            overlap_end = min(block_end_sample, clip.end_sample)

            if overlap_start >= overlap_end:
                break

            self._ensure_current_writer(clip)
            assert self.current_writer is not None

            array_start = overlap_start - block_start_sample
            array_end = overlap_end - block_start_sample
            self.current_writer.write_pcm_i16(pcm[array_start:array_end])
            self.current_written += int(array_end - array_start)

            if overlap_end >= clip.end_sample:
                self._finalize_open_clip(complete=True)
                self.current_index += 1
                continue

            break

    # 함수 설명: 'close' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def close(self) -> None:
        """열어 둔 파일, 오디오 장치, 스레드 등 외부 자원을 정리합니다."""
        self._finalize_open_clip(complete=False)

    def discard_from_sample(self, restart_sample: int) -> list[str]:
        """SegmentedDatasetWriter.discard_from_sample는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        restart_sample = max(0, int(restart_sample))
        discarded_paths: set[str] = set()

        if self.current_writer is not None and self.current_index < len(self.clips):
            current_path = self.clips[self.current_index].path
            self.current_writer.close()
            self.current_writer = None
            self.current_written = 0
            discarded_paths.add(os.path.normcase(os.path.normpath(current_path)))

        for clip in self.clips:
            if clip.end_sample > restart_sample:
                discarded_paths.add(os.path.normcase(os.path.normpath(clip.path)))

        deleted: list[str] = []
        for path_key in sorted(discarded_paths):
            # path_key is normalized for comparison. Recover the original spelling from clips when possible.
            original_path = next(
                (
                    clip.path
                    for clip in self.clips
                    if os.path.normcase(os.path.normpath(clip.path)) == path_key
                ),
                path_key,
            )
            try:
                if os.path.exists(original_path):
                    os.remove(original_path)
                    deleted.append(original_path)
            except OSError as exc:
                print(f"[WARN] failed to delete discarded clip: {original_path} ({exc})")

        discard_rel_paths = {
            os.path.normcase(os.path.normpath(os.path.relpath(path, start=self.dataset_dir)))
            for path in discarded_paths
        }
        self.metadata_rows = [
            row
            for row in self.metadata_rows
            if os.path.normcase(os.path.normpath(row.get("path", ""))) not in discard_rel_paths
        ]
        self.written_clip_paths = [
            path
            for path in self.written_clip_paths
            if os.path.normcase(os.path.normpath(path)) not in discarded_paths
        ]

        self.current_index = len(self.clips)
        for index, clip in enumerate(self.clips):
            if clip.end_sample > restart_sample:
                self.current_index = index
                break
        self.current_writer = None
        self.current_written = 0
        return deleted

    # 함수 설명: '_ensure_current_writer' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def _ensure_current_writer(self, clip: ClipSpec) -> None:
        """SegmentedDatasetWriter._ensure_current_writer는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        if self.current_writer is None:
            os.makedirs(os.path.dirname(clip.path), exist_ok=True)
            self.current_writer = WavPcmWriter(clip.path, self.sample_rate)
            self.current_written = 0

    # 함수 설명: '_finalize_open_clip' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def _finalize_open_clip(self, complete: bool) -> None:
        """SegmentedDatasetWriter._finalize_open_clip는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        if self.current_writer is None:
            return

        clip = self.clips[self.current_index]
        actual_samples = self.current_writer.frames_written
        self.current_writer.close()
        self.current_writer = None

        if actual_samples <= 0:
            self.current_written = 0
            return

        if complete:
            start_sample = clip.start_sample
            end_sample = clip.end_sample
        else:
            start_sample = clip.start_sample
            end_sample = clip.start_sample + actual_samples

        self.written_clip_paths.append(clip.path)

        self.metadata_rows.append(
            make_metadata_row(
                filename=clip.filename,
                path=os.path.relpath(clip.path, start=self.dataset_dir),
                session_name=self.session_name,
                protocol=self.protocol,
                label=clip.label,
                split=clip.split,
                repeat=clip.repeat,
                start_sample=start_sample,
                end_sample=end_sample,
                sample_rate=self.sample_rate,
                adc_center=self.adc_center,
                pcm_gain=self.pcm_gain,
                sample_format=self.sample_format,
                pcm16_gain=self.pcm16_gain,
            )
        )
        self.current_written = 0


# 함수 설명: 'adc_to_pcm_i16' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def adc_to_pcm_i16(adc: np.ndarray, adc_center: int, gain: float) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    centered = adc.astype(np.int32) - int(adc_center)
    pcm = np.rint(centered * float(gain))
    pcm = np.clip(pcm, -32768, 32767)
    return pcm.astype("<i2")


def resolve_packet_sample_format(packet: AudioPacket, requested: str) -> int:
    """내부 상태값을 콘솔이나 그래프에 표시하기 좋은 문자열 또는 라벨로 변환합니다."""
    if requested == "pcm16":
        return AUDIO_FORMAT_PCM16
    if requested == "adc_u16":
        return AUDIO_FORMAT_ADC_U16
    return packet.sample_format


def apply_pcm16_gain(pcm: np.ndarray, gain: float) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    if float(gain) == 1.0:
        return pcm.astype("<i2", copy=True)
    scaled = np.rint(pcm.astype(np.float32) * float(gain))
    scaled = np.clip(scaled, -32768, 32767)
    return scaled.astype("<i2")


def packet_to_pcm_i16(
    packet: AudioPacket,
    requested: str,
    adc_center: int,
    gain: float,
    pcm16_gain: float,
) -> np.ndarray:
    """보드에서 온 ADC/PCM sample을 표시, 저장, 재생에 맞는 PCM/float 형식으로 변환합니다."""
    sample_format = resolve_packet_sample_format(packet, requested)
    if sample_format == AUDIO_FORMAT_PCM16:
        return apply_pcm16_gain(packet.adc.view("<i2"), pcm16_gain)
    return adc_to_pcm_i16(packet.adc, adc_center, gain)


def effective_adc_center_and_gain(args: argparse.Namespace) -> tuple[int, float]:
    """effective_adc_center_and_gain는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    if args.sample_format == "pcm16":
        return 0, args.pcm16_gain
    return args.adc_center, args.pcm_gain


# 함수 설명: 프로토콜별 실제 반복 횟수를 계산합니다. 코/입 단독 수집은 데이터 확보량을 늘리기 위해 2배로 진행합니다.
def effective_protocol_repeats(protocol: str, repeats: int) -> int:
    """effective_protocol_repeats는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    if protocol in ("nasal", "mouth"):
        return repeats * SINGLE_CLASS_PROTOCOL_REPEAT_MULTIPLIER
    return repeats


# 함수 설명: 후속 단계에서 사용할 객체, 배열, 경로, 설정 구조를 구성합니다.
def build_protocol(
    repeats: int = DEFAULT_REPEATS,
    breath_sec: float = DEFAULT_BREATH_SEC,
    pause_sec: float = DEFAULT_PAUSE_SEC,
    protocol: str = DEFAULT_PROTOCOL,
    noise_sec: float = DEFAULT_NOISE_SEC,
) -> list[ProtocolPhase]:
    """입력 설정을 조합해 프로토콜, 모델, feature, 표시 요소 같은 후속 처리 객체를 만듭니다."""
    phases: list[ProtocolPhase] = []
    t = 0.0

    # 함수 설명: 'add' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
    def add(
        duration: float,
        label: str,
        prompt: str,
        repeat: int = 0,
        trim_edges: bool = False,
        save_clip: bool = True,
    ) -> None:
        """build_protocol.add는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        nonlocal t
        phases.append(
            ProtocolPhase(
                start_sec=t,
                end_sec=t + duration,
                label=label,
                prompt=prompt,
                repeat=repeat,
                trim_edges=trim_edges,
                save_clip=save_clip,
            )
        )
        t += duration

    if protocol == "noise":
        for rep in range(1, repeats + 1):
            add(noise_sec, "noise", "주변 소음 또는 실제 생활 소음을 유지하세요", repeat=rep)
        return phases

    if protocol in ("nasal", "mouth"):
        gap_sec = pause_sec / 2.0
        effective_repeats = effective_protocol_repeats(protocol, repeats)
        if protocol == "nasal":
            inhale_label = "nasal_inhale"
            inhale_prompt = "코로 들이마시세요"
            exhale_label = "nasal_exhale"
            exhale_prompt = "코로 내쉬세요"
        else:
            inhale_label = "mouth_inhale"
            inhale_prompt = "입으로 들이마시세요"
            exhale_label = "mouth_exhale"
            exhale_prompt = "입으로 내쉬세요"

        for rep in range(1, effective_repeats + 1):
            add(breath_sec, inhale_label, inhale_prompt, rep, trim_edges=True)
            add(gap_sec, "gap", "호흡을 잠시 멈추고 다음 동작을 준비하세요", rep, save_clip=False)
            add(breath_sec, exhale_label, exhale_prompt, rep, trim_edges=True)
            if rep < effective_repeats:
                add(gap_sec, "gap", "호흡을 잠시 멈추고 다음 동작을 준비하세요", rep, save_clip=False)
        return phases

    raise ValueError(f"unsupported protocol: {protocol}")


# 함수 설명: 후속 단계에서 사용할 객체, 배열, 경로, 설정 구조를 구성합니다.
def make_metadata_row(
    filename: str,
    path: str,
    session_name: str,
    protocol: str,
    label: str,
    split: str,
    repeat: int,
    start_sample: int,
    end_sample: int,
    sample_rate: int,
    adc_center: int,
    pcm_gain: float,
    sample_format: str,
    pcm16_gain: float,
) -> dict[str, str]:
    """make_metadata_row는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    start_sec = start_sample / sample_rate
    end_sec = end_sample / sample_rate
    duration_sec = max(0.0, end_sec - start_sec)

    return {
        "filename": filename,
        "path": path,
        "session": session_name,
        "protocol": protocol,
        "label": label,
        "split": split,
        "repeat": str(repeat),
        "start_sec": f"{start_sec:.3f}",
        "end_sec": f"{end_sec:.3f}",
        "duration_sec": f"{duration_sec:.3f}",
        "sample_rate": str(sample_rate),
        "sample_format": sample_format,
        "adc_center": str(adc_center),
        "pcm_gain": f"{pcm_gain:g}",
        "pcm16_gain": f"{pcm16_gain:g}",
    }


# 함수 설명: 후속 단계에서 사용할 객체, 배열, 경로, 설정 구조를 구성합니다.
def build_clip_specs(
    phases: list[ProtocolPhase],
    dataset_dir: str,
    sample_rate: int,
    edge_trim_sec: float,
    initial_counters: dict[str, int] | None = None,
) -> list[ClipSpec]:
    """입력 설정을 조합해 프로토콜, 모델, feature, 표시 요소 같은 후속 처리 객체를 만듭니다."""
    counters = {label: 0 for label in DATASET_LABELS}
    if initial_counters is not None:
        for label in DATASET_LABELS:
            counters[label] = int(initial_counters.get(label, 0))

    clips: list[ClipSpec] = []

    for phase in phases:
        if not phase.save_clip:
            continue

        trim = edge_trim_sec if phase.trim_edges else 0.0
        clip_start_sec = phase.start_sec + trim
        clip_end_sec = phase.end_sec - trim

        if clip_end_sec <= clip_start_sec:
            continue

        counters[phase.label] += 1
        ordinal = counters[phase.label]
        split = split_for_ordinal(ordinal)
        filename = f"{phase.label}_{ordinal:03d}.wav"
        path = os.path.join(dataset_dir, phase.label, filename)

        clips.append(
            ClipSpec(
                filename=filename,
                label=phase.label,
                split=split,
                repeat=phase.repeat,
                start_sample=int(round(clip_start_sec * sample_rate)),
                end_sample=int(round(clip_end_sec * sample_rate)),
                path=path,
            )
        )

    clips.sort(key=lambda clip: clip.start_sample)
    return clips


# 함수 설명: 'split_for_ordinal' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def split_for_ordinal(ordinal: int) -> str:
    """split_for_ordinal는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    if ordinal <= 0:
        return "train"
    return "test" if ordinal % TEST_EVERY_N == 0 else "train"


# 함수 설명: frame/file 단위 결과를 묶어 요약 통계를 계산합니다.
def summarize_clip_durations(clips: list[ClipSpec], sample_rate: int) -> dict[str, float]:
    """summarize_clip_durations는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    durations = {label: 0.0 for label in DATASET_LABELS}
    for clip in clips:
        durations[clip.label] += clip.expected_samples / sample_rate
    return durations


# 함수 설명: frame/file 단위 결과를 묶어 요약 통계를 계산합니다.
def summarize_clip_split_counts(clips: list[ClipSpec]) -> dict[str, int]:
    """summarize_clip_split_counts는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    counts = {split: 0 for split in SPLITS}
    for clip in clips:
        counts[clip.split] += 1
    return counts


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def describe_protocol(args: argparse.Namespace) -> str:
    """describe_protocol는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    if args.protocol == "noise":
        return f"{args.repeats}x {args.noise_sec:g}s noise"

    class_name = "nasal" if args.protocol == "nasal" else "mouth"
    effective_repeats = effective_protocol_repeats(args.protocol, args.repeats)
    return (
        f"{effective_repeats}x {class_name} inhale/exhale only "
        f"(base {args.repeats}x doubled), "
        f"{args.breath_sec:g}s each + {args.pause_sec / 2.0:g}s unsaved gap, "
        f"{args.edge_trim:g}s edge trim each side"
    )


# 함수 설명: 계산된 결과나 데이터를 파일 또는 출력 장치에 저장합니다.
def write_metadata_csv(path: str, rows: list[dict[str, str]], append: bool = True) -> None:
    """계산된 결과나 설정 값을 CSV, JSON, WAV, C 헤더 같은 출력 파일로 저장합니다."""
    if not rows:
        return

    fieldnames = [
        "filename",
        "path",
        "session",
        "protocol",
        "label",
        "split",
        "repeat",
        "start_sec",
        "end_sec",
        "duration_sec",
        "sample_rate",
        "sample_format",
        "adc_center",
        "pcm_gain",
        "pcm16_gain",
    ]

    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            existing_fieldnames = [(field or "").lstrip("\ufeff") for field in (reader.fieldnames or [])]
            existing_rows = [
                {(key or "").lstrip("\ufeff"): value for key, value in row.items()}
                for row in reader
            ]

        if existing_fieldnames != fieldnames:
            normalized_rows = []
            for existing in existing_rows:
                normalized = {field: existing.get(field, "") for field in fieldnames}
                if not normalized["split"]:
                    normalized["split"] = "legacy"
                normalized_rows.append(normalized)

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(normalized_rows)

    file_has_content = os.path.exists(path) and os.path.getsize(path) > 0
    mode = "a" if append and file_has_content else "w"

    with open(path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if mode == "w":
            writer.writeheader()
        writer.writerows(rows)


# 함수 설명: 'current_phase' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def current_phase(phases: list[ProtocolPhase], audio_sec: float) -> tuple[int, ProtocolPhase]:
    """current_phase는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    for i, phase in enumerate(phases):
        if phase.start_sec <= audio_sec < phase.end_sec:
            return i, phase
    return len(phases) - 1, phases[-1]


# 함수 설명: 'seq_forward_gap' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def seq_forward_gap(expected_seq: int, actual_seq: int) -> int:
    """seq_forward_gap는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
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


# 함수 설명: 시각화 화면이나 그래프 상태를 새 데이터에 맞게 갱신합니다.
def update_amplitude_window(stats: StreamStats, samples: np.ndarray, adc_center: int, sample_format: int) -> None:
    """새로 들어온 데이터에 맞춰 상태, 통계, 그래프 표시를 갱신합니다."""
    if samples.size == 0:
        return

    if sample_format == AUDIO_FORMAT_PCM16:
        values = samples.view("<i2").astype(np.float32)
    else:
        values = samples.astype(np.float32) - float(adc_center)

    value_min = int(values.min())
    value_max = int(values.max())
    stats.window_min = value_min if stats.window_min is None else min(stats.window_min, value_min)
    stats.window_max = value_max if stats.window_max is None else max(stats.window_max, value_max)

    stats.window_sum_sq += float(np.dot(values, values))
    stats.window_samples += int(values.size)


# 함수 설명: 'reset_debug_window' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def reset_debug_window(stats: StreamStats) -> None:
    """누적 상태나 디버그 window를 초기 상태로 되돌립니다."""
    stats.window_packets = 0
    stats.window_min = None
    stats.window_max = None
    stats.window_sum_sq = 0.0
    stats.window_samples = 0


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def print_phase_banner(index: int, total: int, phase: ProtocolPhase, repeats: int) -> None:
    """현재 처리 상태를 사용자가 확인하기 쉬운 콘솔 메시지로 출력합니다."""
    repeat_text = f" ({phase.repeat}/{repeats})" if phase.repeat > 0 else ""
    print()
    print(f"[STEP {index + 1:02d}/{total:02d}] {phase.label}{repeat_text}")
    print(f"  >>> {phase.prompt}")


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def print_debug_line(
    stats: StreamStats,
    phases: list[ProtocolPhase],
    sample_rate: int,
    total_samples: int,
    now: float,
) -> None:
    """현재 처리 상태를 사용자가 확인하기 쉬운 콘솔 메시지로 출력합니다."""
    elapsed = max(now - stats.last_debug_time, 1e-6)
    pps = stats.window_packets / elapsed
    audio_sec = stats.written_samples / sample_rate
    total_sec = total_samples / sample_rate
    _idx, phase = current_phase(phases, min(audio_sec, total_sec - 1e-6))
    remaining = max(0.0, phase.end_sec - audio_sec)

    if stats.window_min is None or stats.window_max is None:
        p2p = 0
    else:
        p2p = stats.window_max - stats.window_min

    if stats.window_samples > 0:
        rms = (stats.window_sum_sq / stats.window_samples) ** 0.5
    else:
        rms = 0.0

    print(
        f"[{audio_sec:6.1f}/{total_sec:.1f}s] "
        f"phase={phase.label:<13} remain={remaining:4.1f}s "
        f"pps={pps:5.1f} dropped={stats.dropped_packets} "
        f"inserted={stats.inserted_samples} p2p={p2p:4d} rms={rms:6.1f}"
    )


# 함수 설명: 파일 시스템이나 장치 목록을 훑어 필요한 항목을 수집합니다.
def scan_existing_clip_counters(dataset_dir: str) -> dict[str, int]:
    """기존 데이터셋 폴더를 훑어 다음 파일 번호나 split 통계를 계산합니다."""
    counters = {label: 0 for label in DATASET_LABELS}

    if not os.path.isdir(dataset_dir):
        return counters

    for current_dir, _dirnames, filenames in os.walk(dataset_dir):
        parent_label = os.path.basename(current_dir)
        if parent_label not in DATASET_LABELS:
            continue

        prefix = f"{parent_label}_"
        suffix = ".wav"

        for filename in filenames:
            if not filename.startswith(prefix) or not filename.endswith(suffix):
                continue

            number_text = filename[len(prefix) : -len(suffix)]
            if not number_text.isdigit():
                continue

            counters[parent_label] = max(counters[parent_label], int(number_text))

    return counters


# 함수 설명: 파일 시스템이나 장치 목록을 훑어 필요한 항목을 수집합니다.
def scan_existing_split_counts(session_dir: str) -> dict[str, dict[str, int]]:
    """기존 데이터셋 폴더를 훑어 다음 파일 번호나 split 통계를 계산합니다."""
    counts = {split: {label: 0 for label in DATASET_LABELS} for split in SPLITS}

    for split in SPLITS:
        for label in DATASET_LABELS:
            label_dir = os.path.join(session_dir, split, label)
            if not os.path.isdir(label_dir):
                continue

            counts[split][label] = len(
                [
                    name
                    for name in os.listdir(label_dir)
                    if name.startswith(f"{label}_") and name.endswith(".wav")
                ]
            )

    return counts


# 함수 설명: 'next_full_session_wav_path' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def next_full_session_wav_path(session_dir: str, session_name: str) -> str:
    """next_full_session_wav_path는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
    base_path = os.path.join(session_dir, f"{session_name}_full.wav")
    if not os.path.exists(base_path):
        return base_path

    index = 2
    while True:
        candidate = os.path.join(session_dir, f"{session_name}_full_{index:03d}.wav")
        if not os.path.exists(candidate):
            return candidate
        index += 1


# 함수 설명: 후속 단계에서 사용할 객체, 배열, 경로, 설정 구조를 구성합니다.
def prepare_dataset_dir(out_dir: str) -> tuple[str, str, dict[str, int], bool]:
    """수집이나 추론에 들어가기 전 경로, 버퍼, 입력 프레임을 필요한 형태로 준비합니다."""
    dataset_dir = out_dir
    metadata_path = os.path.join(dataset_dir, "metadata.csv")
    existed = os.path.exists(dataset_dir)

    if existed and not os.path.isdir(dataset_dir):
        raise FileExistsError(
            f"dataset path exists but is not a directory: {dataset_dir}. "
            "Use a different --out-dir."
        )

    os.makedirs(dataset_dir, exist_ok=True)
    for label in DATASET_LABELS:
        os.makedirs(os.path.join(dataset_dir, label), exist_ok=True)

    counters = scan_existing_clip_counters(dataset_dir)
    return dataset_dir, metadata_path, counters, existed


# 함수 설명: 보드나 출력 장치로 제어 명령 또는 데이터 패킷을 전송합니다.
def send_board_ai_inference_command(ser: serial.Serial, mode: str) -> None:
    """STM32나 보조 보드로 한 줄 제어 명령을 보내고 전송 버퍼를 비웁니다."""
    if mode == "keep":
        return

    command = "AI ON\n" if mode == "on" else "AI OFF\n"
    ser.write(command.encode("ascii"))
    ser.flush()
    print(f"[board] sent {command.strip()} for live AI inference", flush=True)
    time.sleep(0.05)


# 함수 설명: 'collect_dataset' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def collect_dataset(args: argparse.Namespace) -> int:
    """사용자가 선택한 모드의 실제 수집, 테스트, 모니터링 루프를 실행합니다."""
    if serial is None:
        raise DependencyError("pyserial is not installed. Install it with: pip install pyserial")

    display_repeats = effective_protocol_repeats(args.protocol, args.repeats)
    phases = build_protocol(
        repeats=args.repeats,
        breath_sec=args.breath_sec,
        pause_sec=args.pause_sec,
        protocol=args.protocol,
        noise_sec=args.noise_sec,
    )
    total_duration_sec = phases[-1].end_sec
    total_samples = int(round(total_duration_sec * args.sample_rate))

    planned_dataset_dir = args.out_dir
    planned_metadata_path = os.path.join(planned_dataset_dir, "metadata.csv")
    planned_existing_counters = scan_existing_clip_counters(planned_dataset_dir)
    planned_session_wav_path = next_full_session_wav_path(planned_dataset_dir, args.name)
    planned_clips = build_clip_specs(
        phases,
        planned_dataset_dir,
        args.sample_rate,
        args.edge_trim,
        initial_counters=planned_existing_counters,
    )
    planned_durations = summarize_clip_durations(planned_clips, args.sample_rate)
    planned_split_counts = summarize_clip_split_counts(planned_clips)

    packets_per_half = (args.half_buffer_samples + args.packet_samples - 1) // args.packet_samples
    short_packet_samples = args.half_buffer_samples - args.packet_samples * (packets_per_half - 1)
    if short_packet_samples <= 0:
        short_packet_samples = args.packet_samples
    metadata_adc_center, metadata_pcm_gain = effective_adc_center_and_gain(args)

    print("=== Breath Dataset Collector ===")
    print(f"Port              : {args.port}")
    print(f"Dataset dir       : {planned_dataset_dir}")
    print(f"Session name      : {args.name}")
    print(f"Append existing   : {'yes' if os.path.isdir(planned_dataset_dir) else 'no'}")
    print(f"Metadata CSV      : {planned_metadata_path}")
    print(f"Full session WAV  : {planned_session_wav_path if args.save_session_wav else 'off'}")
    print(f"Sample rate       : {args.sample_rate} Hz")
    print(f"Duration          : {total_duration_sec:.1f} sec")
    print(f"Quick 5 protocol  : {'on' if args.quick_5 else 'off'}")
    print(f"Protocol preset   : {args.protocol}")
    print("Storage layout    : dataset/<label>/<label>_NNN.wav")
    print("Train/test split  : 8:2 by clip ordinal in feature extraction")
    print("Post processing   : off, collection only")
    print(f"Board AI inference: {args.ai_inference}")
    print(f"Sample format     : {args.sample_format}")
    print(f"PCM16 gain        : {args.pcm16_gain}")
    print(f"Audio monitor     : {'on' if args.play_audio else 'off'}")
    if args.play_audio:
        print(f"Playback gain     : {args.playback_gain:g}")
        print("Playback warning  : use headphones to avoid recording speaker feedback")
    print(f"Protocol          : {describe_protocol(args)}")
    print(
        "Usable durations  : "
        + ", ".join(
            f"{label}={seconds:.1f}s"
            for label, seconds in planned_durations.items()
            if seconds > 0
        )
    )
    print(f"Clip count        : {len(planned_clips)}")
    print(
        "Planned split     : "
        + ", ".join(f"{split}={planned_split_counts[split]}" for split in SPLITS)
    )
    print(
        "Next clip numbers : "
        + ", ".join(f"{label}={planned_existing_counters[label] + 1}" for label in DATASET_LABELS)
    )
    print(f"ADC center        : {metadata_adc_center}")
    print(f"PCM gain          : {metadata_pcm_gain}")
    print("Drop fill         : on")
    print(f"Startup warmup    : {args.warmup_sec:g}s discarded before recording")
    if args.pause_key:
        if console_hotkeys_available():
            print(f"Pause/retry key   : {args.pause_key} then Enter to retry the current STEP")
        else:
            print("Pause/retry key   : unavailable on this console")
    else:
        print("Pause/retry key   : off")
    print()

    if not args.start_now:
        input("준비가 되면 Enter를 누르세요. 마이크 warmup 후 녹음 안내가 시작됩니다...")

    ser = serial.Serial(args.port, args.baudrate, timeout=args.serial_timeout)
    audio_player: LivePcmPlayer | None = None
    session_writer: WavPcmWriter | None = None
    segment_writer: SegmentedDatasetWriter | None = None
    try:
        dataset_dir, metadata_path, existing_counters, dataset_existed = prepare_dataset_dir(args.out_dir)
        clips = build_clip_specs(
            phases,
            dataset_dir,
            args.sample_rate,
            args.edge_trim,
            initial_counters=existing_counters,
        )
        session_wav_path = next_full_session_wav_path(dataset_dir, args.name)
        session_writer = WavPcmWriter(session_wav_path, args.sample_rate) if args.save_session_wav else None
        segment_writer = SegmentedDatasetWriter(
            clips=clips,
            sample_rate=args.sample_rate,
            adc_center=metadata_adc_center,
            pcm_gain=metadata_pcm_gain,
            sample_format=args.sample_format,
            pcm16_gain=args.pcm16_gain,
            session_name=args.name,
            protocol=args.protocol,
            dataset_dir=dataset_dir,
        )
        if args.play_audio:
            audio_player = LivePcmPlayer(
                sample_rate=args.sample_rate,
                queue_sec=args.playback_queue_sec,
                gain=args.playback_gain,
            )
    except Exception:
        if audio_player is not None:
            audio_player.close()
        if segment_writer is not None:
            try:
                segment_writer.close()
            except Exception:
                pass
        try:
            if session_writer is not None:
                session_writer.close()
        except Exception:
            pass
        ser.close()
        raise

    assert segment_writer is not None
    receiver = AudioPacketReceiver(ser, max_packet_samples=args.max_packet_samples)
    stats = StreamStats(last_debug_time=time.monotonic())
    active_phase_index = -1
    completed = False

    # 함수 설명: 계산된 결과나 데이터를 파일 또는 출력 장치에 저장합니다.
    def write_timeline_block(
        pcm: np.ndarray,
        raw_for_debug: np.ndarray | None = None,
        sample_format_for_debug: int = AUDIO_FORMAT_ADC_U16,
    ) -> None:
        """계산된 결과나 설정 값을 CSV, JSON, WAV, C 헤더 같은 출력 파일로 저장합니다."""
        nonlocal active_phase_index

        if pcm.size == 0:
            return

        block_start = stats.written_samples

        if session_writer is not None:
            session_writer.write_pcm_i16(pcm)

        segment_writer.write_block(block_start, pcm)
        if audio_player is not None:
            audio_player.write(pcm)
        stats.written_samples += int(pcm.size)

        if raw_for_debug is not None:
            update_amplitude_window(stats, raw_for_debug, args.adc_center, sample_format_for_debug)

        audio_sec = min(stats.written_samples / args.sample_rate, total_duration_sec - 1e-6)
        phase_index, phase = current_phase(phases, audio_sec)
        if phase_index != active_phase_index:
            active_phase_index = phase_index
            print_phase_banner(active_phase_index, len(phases), phase, display_repeats)

        now = time.monotonic()
        if now - stats.last_debug_time >= args.debug_interval:
            print_debug_line(stats, phases, args.sample_rate, total_samples, now)
            reset_debug_window(stats)
            stats.last_debug_time = now

    def warmup_input_stream() -> None:
        """collect_dataset.warmup_input_stream는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        if args.warmup_sec <= 0:
            return

        warmup_stats = StreamStats(last_debug_time=time.monotonic())
        deadline = time.monotonic() + float(args.warmup_sec)
        print(f"Mic warmup: discarding startup audio for {args.warmup_sec:g}s before STEP 01...")

        while time.monotonic() < deadline:
            try:
                packet = receiver.read_packet()
            except TimeoutError:
                continue

            warmup_stats.total_packets += 1
            warmup_stats.window_packets += 1
            warmup_stats.received_samples += packet.samples

            sample_format = resolve_packet_sample_format(packet, args.sample_format)
            if audio_player is not None:
                pcm = packet_to_pcm_i16(
                    packet,
                    args.sample_format,
                    args.adc_center,
                    args.pcm_gain,
                    args.pcm16_gain,
                )
                audio_player.write(pcm)
            update_amplitude_window(warmup_stats, packet.adc, args.adc_center, sample_format)

        if warmup_stats.window_samples > 0:
            rms = (warmup_stats.window_sum_sq / warmup_stats.window_samples) ** 0.5
            p2p = (warmup_stats.window_max or 0) - (warmup_stats.window_min or 0)
            print(
                "Mic warmup done: "
                f"packets={warmup_stats.total_packets} "
                f"samples={warmup_stats.received_samples} "
                f"p2p={p2p:.0f} rms={rms:.1f}"
            )
        else:
            print("Mic warmup done: no audio packets received")

        ser.reset_input_buffer()

    def pause_key_pressed() -> bool:
        """collect_dataset.pause_key_pressed는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        if not args.pause_key or not console_hotkeys_available():
            return False

        key = poll_console_key()
        return key is not None and key.lower() == args.pause_key

    def wait_resume_enter() -> None:
        """collect_dataset.wait_resume_enter는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        clear_console_keys()
        if console_hotkeys_available():
            while True:
                key = poll_console_key()
                if key in ("\r", "\n"):
                    return
                if key == "\x03":
                    raise KeyboardInterrupt
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass
                time.sleep(0.05)

        input()
        ser.reset_input_buffer()

    def pause_and_retry_current_step() -> None:
        """collect_dataset.pause_and_retry_current_step는 이 파일의 처리 흐름 중 입력값을 검증하거나 변환해 다음 단계로 넘깁니다."""
        nonlocal active_phase_index

        audio_sec = min(stats.written_samples / args.sample_rate, total_duration_sec - 1.0e-6)
        phase_index, phase = current_phase(phases, audio_sec)
        restart_sample = int(round(phase.start_sec * args.sample_rate))
        deleted_paths = segment_writer.discard_from_sample(restart_sample)

        stats.written_samples = restart_sample
        stats.expected_seq = None
        stats.short_packet_mod = None
        active_phase_index = -1
        reset_debug_window(stats)
        stats.last_debug_time = time.monotonic()

        try:
            ser.reset_input_buffer()
        except Exception:
            pass

        print()
        print(f"[PAUSE] STEP {phase_index + 1:02d}/{len(phases):02d} {phase.label} 재녹음 대기")
        if phase.save_clip:
            if deleted_paths:
                for path in deleted_paths:
                    print(f"[PAUSE] deleted clip: {path}")
            else:
                print("[PAUSE] deleted clip: none yet, same STEP will restart")
        else:
            print("[PAUSE] current STEP is an unsaved gap; no clip file was deleted")
        if session_writer is not None:
            print("[PAUSE] note: --save-session-wav full-session WAV keeps the discarded raw time")
        print("[PAUSE] Enter를 누르면 같은 STEP부터 다시 시작합니다. Ctrl+C는 전체 중단입니다.")
        wait_resume_enter()
        stats.last_debug_time = time.monotonic()
        print("[RESUME] 같은 STEP부터 다시 녹음합니다.")

    try:
        time.sleep(args.open_delay)
        send_board_ai_inference_command(ser, args.ai_inference)
        ser.reset_input_buffer()
        warmup_input_stream()
        stats.last_debug_time = time.monotonic()
        print("STM32 audio packet sync 대기 중...")

        while stats.written_samples < total_samples:
            if pause_key_pressed():
                pause_and_retry_current_step()
                continue

            packet = receiver.read_packet()

            if packet.samples != args.packet_samples:
                stats.short_packet_mod = packet.seq % packets_per_half

            if stats.expected_seq is not None and packet.seq != stats.expected_seq:
                gap = seq_forward_gap(stats.expected_seq, packet.seq)

                if 0 < gap <= args.max_fill_gap_packets:
                    stats.dropped_packets += gap
                    missing_samples = estimate_missing_samples(
                        first_missing_seq=stats.expected_seq,
                        missing_packets=gap,
                        packet_samples=args.packet_samples,
                        packets_per_half=packets_per_half,
                        short_packet_samples=short_packet_samples,
                        short_packet_mod=stats.short_packet_mod,
                    )

                    remaining = total_samples - stats.written_samples
                    insert_count = min(missing_samples, remaining)
                    if insert_count > 0:
                        silence = np.zeros(insert_count, dtype="<i2")
                        stats.inserted_samples += insert_count
                        write_timeline_block(silence)

                    print(
                        f"[WARN] seq jump: expected={stats.expected_seq}, "
                        f"got={packet.seq}, missing_packets={gap}, "
                        f"inserted_samples={insert_count}"
                    )
                else:
                    stats.resync_events += 1
                    print(
                        f"[WARN] seq resync/reset: expected={stats.expected_seq}, "
                        f"got={packet.seq}, modular_gap={gap}"
                    )

            stats.expected_seq = (packet.seq + 1) % UINT32_MOD
            stats.total_packets += 1
            stats.window_packets += 1
            stats.received_samples += packet.samples

            remaining = total_samples - stats.written_samples
            if remaining <= 0:
                break

            raw = packet.adc[:remaining]
            sample_format = resolve_packet_sample_format(packet, args.sample_format)
            pcm = packet_to_pcm_i16(
                AudioPacket(seq=packet.seq, samples=raw.size, adc=raw, sample_format=packet.sample_format),
                args.sample_format,
                args.adc_center,
                args.pcm_gain,
                args.pcm16_gain,
            )
            write_timeline_block(pcm, raw_for_debug=raw, sample_format_for_debug=sample_format)
            if pause_key_pressed():
                pause_and_retry_current_step()

        completed = stats.written_samples >= total_samples

    except KeyboardInterrupt:
        print("\n[STOP] 사용자 중단")
    finally:
        try:
            if audio_player is not None:
                audio_player.close()
            if segment_writer is not None:
                segment_writer.close()
            if session_writer is not None:
                session_writer.close()
        finally:
            ser.close()

    write_metadata_csv(metadata_path, segment_writer.metadata_rows)

    recorded_sec = stats.written_samples / args.sample_rate

    print()
    print("=== Summary ===")
    print(f"completed       : {completed}")
    print(f"recorded_sec    : {recorded_sec:.3f}")
    print(f"packets         : {stats.total_packets}")
    print(f"received_samples: {stats.received_samples}")
    print(f"written_samples : {stats.written_samples}")
    print(f"dropped_packets : {stats.dropped_packets}")
    print(f"inserted_samples: {stats.inserted_samples}")
    print(f"resync_events   : {stats.resync_events}")
    if audio_player is not None:
        print(f"playback_dropped: {audio_player.dropped_buffers}")
    print(f"clips_expected  : {len(clips)}")
    print(f"clips_written   : {len(segment_writer.metadata_rows)}")
    print(f"append_existing : {dataset_existed}")
    print(f"dataset_dir     : {dataset_dir}")
    print(f"metadata_csv    : {metadata_path}")
    if args.save_session_wav:
        print(f"session_wav     : {session_wav_path}")

    return 0 if completed else 2


# 함수 설명: 명령행 옵션을 정의하고 사용자가 입력한 인자를 파싱합니다.
def parse_args(argv: list[str]) -> argparse.Namespace:
    """명령행에서 받을 옵션과 기본값을 정의하고 argparse 객체로 반환합니다."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    parser = argparse.ArgumentParser(
        description="Collect class-separated breath WAV clips from STM32 USB CDC packets."
    )
    parser.add_argument("port", help="STM32 USB CDC COM port, e.g. COM5")
    parser.add_argument("--out-dir", default="dataset", help="unified dataset root directory")
    parser.add_argument("--name", default=f"breath_{timestamp}", help="collection session name for metadata/full-session WAV")
    parser.add_argument("--save-session-wav", action="store_true", help="also save one full-session WAV")
    parser.add_argument(
        "--ai-inference",
        choices=("off", "on", "keep"),
        default="off",
        help="send AI OFF/ON to the board after opening COM; default off for cleaner data collection",
    )
    parser.add_argument("--baudrate", type=int, default=115200, help="ignored by USB CDC, required by pyserial")
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument(
        "--sample-format",
        choices=SAMPLE_FORMAT_CHOICES,
        default="auto",
        help="audio payload format: auto uses packet reserved field, pcm16 is for I2S test streaming",
    )
    parser.add_argument("--adc-center", type=int, default=DEFAULT_ADC_CENTER)
    parser.add_argument("--pcm-gain", type=float, default=DEFAULT_PCM_GAIN)
    parser.add_argument(
        "--pcm16-gain",
        type=float,
        default=DEFAULT_PCM16_GAIN,
        help="fixed digital gain for pcm16/I2S samples; keep this constant for model training and live validation",
    )
    parser.add_argument(
        "--play-audio",
        action="store_true",
        help="play the PCM being saved during collection; use headphones to avoid speaker feedback in the dataset",
    )
    parser.add_argument(
        "--playback-gain",
        type=float,
        default=1.0,
        help="monitor-only playback gain; does not change saved WAV data",
    )
    parser.add_argument(
        "--playback-queue-sec",
        type=float,
        default=0.75,
        help="maximum live playback queue length before old audio buffers are dropped",
    )
    parser.add_argument(
        "--protocol",
        choices=PROTOCOL_CHOICES,
        default=DEFAULT_PROTOCOL,
        help="collection protocol preset: nasal, mouth, or noise",
    )
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, help="breathing protocol repeat count; recommended 10 to 15")
    parser.add_argument("--quick-5", action="store_true", help="shortcut protocol: 5 repeats for the selected protocol")
    parser.add_argument("--breath-sec", type=float, default=DEFAULT_BREATH_SEC, help="duration of each breath phase")
    parser.add_argument(
        "--pause-sec",
        type=float,
        default=DEFAULT_PAUSE_SEC,
        help="nasal/mouth: half of this value is used as an unsaved gap",
    )
    parser.add_argument("--noise-sec", type=float, default=DEFAULT_NOISE_SEC, help="duration of each noise segment for --protocol noise")
    parser.add_argument("--edge-trim", type=float, default=DEFAULT_EDGE_TRIM_SEC, help="seconds removed from both edges of each breath phase")
    parser.add_argument("--start-now", action="store_true", help="do not wait for Enter before recording")
    parser.add_argument("--open-delay", type=float, default=2.0, help="delay after opening serial port")
    parser.add_argument(
        "--warmup-sec",
        type=float,
        default=2.0,
        help="seconds of startup audio to discard after opening COM and before recording STEP 01",
    )
    parser.add_argument("--serial-timeout", type=float, default=0.05)
    parser.add_argument("--debug-interval", type=float, default=1.0)
    parser.add_argument("--packet-samples", type=int, default=DEFAULT_PACKET_SAMPLES)
    parser.add_argument("--half-buffer-samples", type=int, default=DEFAULT_HALF_BUFFER_SAMPLES)
    parser.add_argument("--max-packet-samples", type=int, default=4096)
    parser.add_argument("--max-fill-gap-packets", type=int, default=1000)
    parser.add_argument(
        "--pause-key",
        default="p",
        help=(
            "single console key that pauses collection and retries the current STEP; "
            "use 'off' to disable"
        ),
    )
    args = parser.parse_args(argv)
    if args.quick_5:
        args.repeats = QUICK_REPEATS

    if args.repeats <= 0:
        parser.error("--repeats must be greater than 0")
    if args.breath_sec <= 0:
        parser.error("--breath-sec must be greater than 0")
    if args.pause_sec <= 0:
        parser.error("--pause-sec must be greater than 0")
    if args.noise_sec <= 0:
        parser.error("--noise-sec must be greater than 0")
    if args.playback_gain <= 0:
        parser.error("--playback-gain must be greater than 0")
    if args.playback_queue_sec <= 0:
        parser.error("--playback-queue-sec must be greater than 0")
    if args.warmup_sec < 0:
        parser.error("--warmup-sec must be 0 or greater")
    if args.edge_trim < 0:
        parser.error("--edge-trim must be 0 or greater")
    if args.edge_trim * 2.0 >= args.breath_sec:
        parser.error("--edge-trim is too large; usable breath duration would be zero or negative")
    if args.sample_rate <= 0:
        parser.error("--sample-rate must be greater than 0")
    pause_key = str(args.pause_key).strip()
    if pause_key.lower() in ("", "off", "none", "disable", "disabled"):
        args.pause_key = ""
    elif len(pause_key) != 1:
        parser.error("--pause-key must be one character, or 'off'")
    else:
        args.pause_key = pause_key.lower()

    return args


# 함수 설명: 스크립트 진입점으로 인자를 읽고 전체 실행 흐름을 호출합니다.
def main(argv: list[str] | None = None) -> int:
    """스크립트 진입점으로 CLI 인자를 읽고 전체 실행 흐름을 순서대로 호출합니다."""
    configure_utf8_stdio()
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        return collect_dataset(args)
    except SerialException as exc:
        print(f"[ERROR] serial error: {exc}", file=sys.stderr)
        return 1
    except DependencyError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except FileExistsError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except TimeoutError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
