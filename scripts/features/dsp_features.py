# -*- coding: utf-8 -*-
"""오프라인 학습과 실시간 검증이 공유하는 호흡음 DSP 특징 추출 유틸리티입니다.

16 kHz WAV를 float32로 정규화하고, 50~2500 Hz 대역통과 필터, 프레임 분할, 스펙트럼 특징, MFCC, 선택적 노이즈 프로파일 보정을 한곳에서 수행합니다. STM32 펌웨어로 이식해야 하는 계산식의 기준 파일입니다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import fftpack, signal
from scipy.io import wavfile


SAMPLE_RATE = 16000
FRAME_SIZE = 1024
HOP_SIZE = 512

BPF_LOW_HZ = 50.0
BPF_HIGH_HZ = 2500.0
BPF_ORDER = 4

ROLLOFF_RATIO = 0.85
EPS = 1.0e-12

FFT_SIZE = FRAME_SIZE
WINDOW_TYPE = "hann"

ENERGY_BANDS = (
    ("energy_50_300", "low_ratio", "snr_50_300_db", 50.0, 300.0),
    ("energy_300_800", "mid_ratio", "snr_300_800_db", 300.0, 800.0),
    ("energy_800_2000", "high_ratio", "snr_800_2000_db", 800.0, 2000.0),
    ("energy_2000_4000", "very_high_ratio", None, 2000.0, 4000.0),
)

MFCC_FMIN_HZ = 50.0
MFCC_FMAX_HZ = 4000.0
NUM_MELS = 26
NUM_MFCC = 13

BASE_FEATURE_COLUMNS = [
    "rms",
    "log_rms",
    "zcr",
    "spectral_centroid",
    "spectral_bandwidth",
    "spectral_flatness",
    "rolloff_85",
    "dominant_freq",
    "total_energy",
    "energy_50_300",
    "energy_300_800",
    "energy_800_2000",
    "energy_2000_4000",
    "low_ratio",
    "mid_ratio",
    "high_ratio",
    "very_high_ratio",
] + [f"mfcc_{i}" for i in range(1, NUM_MFCC + 1)]

NOISE_FEATURE_COLUMNS = [
    "snr_total_db",
    "snr_50_300_db",
    "snr_300_800_db",
    "snr_800_2000_db",
    "spectral_subtracted_energy",
]


@dataclass(frozen=True)
class NoiseProfile:
    """노이즈 WAV들에서 계산한 평균 파워 스펙트럼과 생성 당시 DSP 설정을 함께 보관합니다."""
    path: Path
    freqs: np.ndarray
    mean_power: np.ndarray
    noise_floor_db: np.ndarray
    sample_rate: int
    frame_size: int
    hop_size: int
    fft_size: int
    window_type: str
    bpf_low_hz: float
    bpf_high_hz: float
    bpf_order: int
    file_count: int
    frame_count: int


def pcm_to_float32(data: np.ndarray) -> np.ndarray:
    """WAV PCM 또는 float 샘플을 -1.0~1.0 범위의 float32 파형으로 변환합니다."""
    if np.issubdtype(data.dtype, np.floating):
        return np.clip(data.astype(np.float32), -1.0, 1.0)
    if data.dtype == np.int16:
        return data.astype(np.float32) / 32768.0
    if data.dtype == np.int32:
        return data.astype(np.float32) / 2147483648.0
    if data.dtype == np.uint8:
        return (data.astype(np.float32) - 128.0) / 128.0
    if np.issubdtype(data.dtype, np.integer):
        info = np.iinfo(data.dtype)
        peak = max(abs(info.min), abs(info.max))
        return data.astype(np.float32) / float(peak)
    raise TypeError(f"unsupported WAV dtype: {data.dtype}")


def read_wav_as_float32(path: Path, expected_sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """WAV 파일을 읽고 샘플레이트와 채널 수를 검증한 뒤 단일 채널 float32 배열로 반환합니다."""
    sample_rate, data = wavfile.read(path)
    if sample_rate != expected_sample_rate:
        raise ValueError(f"sample rate mismatch: expected {expected_sample_rate}, got {sample_rate}")

    audio = pcm_to_float32(data)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    if audio.size == 0:
        raise ValueError("empty WAV")
    return np.ascontiguousarray(audio, dtype=np.float32)


def design_bandpass_filter(
    sample_rate: int = SAMPLE_RATE,
    low_hz: float = BPF_LOW_HZ,
    high_hz: float = BPF_HIGH_HZ,
    order: int = BPF_ORDER,
) -> np.ndarray:
    """호흡음 특징 추출에 쓰는 Butterworth SOS 대역통과 필터 계수를 만듭니다."""
    nyquist = sample_rate * 0.5
    if not (0.0 < low_hz < high_hz < nyquist):
        raise ValueError("invalid band-pass cutoff frequencies")
    return signal.butter(order, [low_hz / nyquist, high_hz / nyquist], btype="bandpass", output="sos")


def apply_bandpass(audio: np.ndarray, sos: np.ndarray, causal: bool = False) -> np.ndarray:
    """오프라인 zero-phase 또는 실시간 causal 방식으로 대역통과 필터를 적용합니다."""
    if causal:
        filtered = signal.sosfilt(sos, audio)
    else:
        try:
            filtered = signal.sosfiltfilt(sos, audio)
        except ValueError:
            filtered = signal.sosfilt(sos, audio)
    return np.ascontiguousarray(filtered, dtype=np.float32)


def hz_to_mel(hz: np.ndarray | float) -> np.ndarray | float:
    """Hz 주파수를 MFCC 필터뱅크 계산에 쓰는 mel 축 값으로 바꿉니다."""
    return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)


def mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    """mel 축 값을 실제 Hz 주파수로 되돌립니다."""
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def build_mel_filterbank(
    sample_rate: int = SAMPLE_RATE,
    fft_size: int = FFT_SIZE,
    num_mels: int = NUM_MELS,
    fmin_hz: float = MFCC_FMIN_HZ,
    fmax_hz: float = MFCC_FMAX_HZ,
) -> np.ndarray:
    """FFT power bin을 mel band 에너지로 합산하기 위한 삼각 필터뱅크를 생성합니다."""
    freqs = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
    mel_min = hz_to_mel(fmin_hz)
    mel_max = hz_to_mel(fmax_hz)
    mel_points = np.linspace(mel_min, mel_max, num_mels + 2)
    hz_points = mel_to_hz(mel_points)

    filterbank = np.zeros((num_mels, freqs.size), dtype=np.float32)
    for i in range(num_mels):
        left = hz_points[i]
        center = hz_points[i + 1]
        right = hz_points[i + 2]
        left_slope = (freqs - left) / max(center - left, EPS)
        right_slope = (right - freqs) / max(right - center, EPS)
        filterbank[i, :] = np.maximum(0.0, np.minimum(left_slope, right_slope)).astype(np.float32)
    return filterbank


def frame_signal(audio: np.ndarray, frame_size: int = FRAME_SIZE, hop_size: int = HOP_SIZE) -> list[tuple[int, np.ndarray]]:
    """전체 파형을 고정 길이 프레임과 hop 간격으로 자르고 짧은 입력은 0으로 패딩합니다."""
    if audio.size < frame_size:
        padded = np.zeros(frame_size, dtype=np.float32)
        padded[: audio.size] = audio
        return [(0, padded)]

    frames: list[tuple[int, np.ndarray]] = []
    last_start = audio.size - frame_size
    for start in range(0, last_start + 1, hop_size):
        frames.append((start, audio[start : start + frame_size]))
    return frames


def zero_crossing_rate(frame: np.ndarray) -> float:
    """프레임 안에서 부호가 바뀌는 비율을 계산해 거친 시간 영역 특징으로 사용합니다."""
    signs = np.signbit(frame)
    return float(np.mean(signs[1:] != signs[:-1]))


def spectrum_freqs(sample_rate: int = SAMPLE_RATE, fft_size: int = FFT_SIZE) -> np.ndarray:
    """현재 FFT 크기와 샘플레이트 기준의 rFFT 주파수 bin 배열을 반환합니다."""
    return np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)


def compute_spectrum(frame: np.ndarray, window: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """윈도우를 곱한 프레임에서 rFFT와 power spectrum을 계산합니다."""
    windowed = frame * window
    spectrum = np.fft.rfft(windowed, n=FFT_SIZE)
    power = (np.abs(spectrum) ** 2).astype(np.float64)
    return spectrum_freqs(), power


def band_energy(freqs: np.ndarray, power: np.ndarray, low_hz: float, high_hz: float) -> float:
    """지정한 주파수 대역의 power를 합산해 band energy 특징을 만듭니다."""
    mask = (freqs >= low_hz) & (freqs < high_hz)
    return float(np.sum(power[mask]))


def compute_mfcc(power: np.ndarray, mel_filterbank: np.ndarray) -> np.ndarray:
    """mel 에너지에 log와 DCT를 적용해 NUM_MFCC개의 MFCC 계수를 계산합니다."""
    mel_energy = mel_filterbank @ power
    log_mel_energy = np.log(mel_energy + EPS)
    mfcc = fftpack.dct(log_mel_energy, type=2, norm="ortho")[:NUM_MFCC]
    return mfcc.astype(np.float64)


def power_db(power: np.ndarray | float) -> np.ndarray | float:
    """power 값을 dB 스케일로 변환하되 0 나눗셈을 EPS로 방지합니다."""
    return 10.0 * np.log10(np.asarray(power) + EPS)


def snr_db(signal_power: float, noise_power: float) -> float:
    """신호 power와 노이즈 power의 비율을 dB 단위 SNR로 계산합니다."""
    return float(10.0 * np.log10((float(signal_power) + EPS) / (float(noise_power) + EPS)))


def validate_noise_profile(profile: NoiseProfile) -> None:
    """저장된 노이즈 프로파일이 현재 특징 추출 상수와 호환되는지 검증합니다."""
    expected_freqs = spectrum_freqs()
    if profile.sample_rate != SAMPLE_RATE:
        raise ValueError(f"noise profile sample_rate mismatch: {profile.sample_rate} != {SAMPLE_RATE}")
    if profile.frame_size != FRAME_SIZE or profile.hop_size != HOP_SIZE or profile.fft_size != FFT_SIZE:
        raise ValueError("noise profile frame/hop/fft settings do not match the feature pipeline")
    if profile.window_type != WINDOW_TYPE:
        raise ValueError(f"noise profile window mismatch: {profile.window_type} != {WINDOW_TYPE}")
    if abs(profile.bpf_low_hz - BPF_LOW_HZ) > 1.0e-6 or abs(profile.bpf_high_hz - BPF_HIGH_HZ) > 1.0e-6:
        raise ValueError("noise profile band-pass settings do not match the feature pipeline")
    if profile.bpf_order != BPF_ORDER:
        raise ValueError(f"noise profile filter order mismatch: {profile.bpf_order} != {BPF_ORDER}")
    if profile.mean_power.shape != expected_freqs.shape or not np.allclose(profile.freqs, expected_freqs):
        raise ValueError("noise profile frequency bins do not match the feature pipeline")


def load_noise_profile(path: Path | None) -> NoiseProfile | None:
    """npz 노이즈 프로파일을 읽어 NoiseProfile로 복원하고 설정 호환성을 확인합니다."""
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"noise profile not found: {path}")

    data = np.load(path, allow_pickle=False)
    profile = NoiseProfile(
        path=path,
        freqs=np.asarray(data["freqs"], dtype=np.float64),
        mean_power=np.asarray(data["mean_power"], dtype=np.float64),
        noise_floor_db=np.asarray(data["noise_floor_db"], dtype=np.float64),
        sample_rate=int(data["sample_rate"]),
        frame_size=int(data["frame_size"]),
        hop_size=int(data["hop_size"]),
        fft_size=int(data["fft_size"]),
        window_type=str(data["window_type"]),
        bpf_low_hz=float(data["bpf_low_hz"]),
        bpf_high_hz=float(data["bpf_high_hz"]),
        bpf_order=int(data["bpf_order"]),
        file_count=int(data["file_count"]),
        frame_count=int(data["frame_count"]),
    )
    validate_noise_profile(profile)
    return profile


def subtract_noise_power(power: np.ndarray, noise_profile: NoiseProfile | None) -> np.ndarray:
    """노이즈 프로파일이 있으면 평균 노이즈 power를 빼고 음수는 0으로 클램프합니다."""
    if noise_profile is None:
        return power
    return np.maximum(power - noise_profile.mean_power, 0.0)


def extract_signal_features(
    frame: np.ndarray,
    window: np.ndarray,
    mel_filterbank: np.ndarray,
    noise_profile: NoiseProfile | None = None,
) -> dict[str, float]:
    """한 프레임에서 RMS, 스펙트럼, band ratio, MFCC, 선택적 SNR 특징을 모두 계산합니다."""
    rms = float(np.sqrt(np.mean(frame * frame) + EPS))
    log_rms = float(np.log(rms + EPS))
    zcr = zero_crossing_rate(frame)

    freqs, raw_power = compute_spectrum(frame, window)
    feature_power = subtract_noise_power(raw_power, noise_profile)
    total_energy = float(np.sum(feature_power) + EPS)

    centroid = float(np.sum(freqs * feature_power) / total_energy)
    bandwidth = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * feature_power) / total_energy))
    flatness = float(np.exp(np.mean(np.log(feature_power + EPS))) / (np.mean(feature_power) + EPS))

    cumulative = np.cumsum(feature_power)
    rolloff_idx = int(np.searchsorted(cumulative, ROLLOFF_RATIO * total_energy))
    rolloff_idx = min(rolloff_idx, freqs.size - 1)
    dominant_freq = float(freqs[int(np.argmax(feature_power))])

    features: dict[str, float] = {
        "rms": rms,
        "log_rms": log_rms,
        "zcr": zcr,
        "spectral_centroid": centroid,
        "spectral_bandwidth": bandwidth,
        "spectral_flatness": flatness,
        "rolloff_85": float(freqs[rolloff_idx]),
        "dominant_freq": dominant_freq,
        "total_energy": total_energy,
    }

    for energy_name, ratio_name, _snr_name, low_hz, high_hz in ENERGY_BANDS:
        energy = band_energy(freqs, feature_power, low_hz, high_hz)
        features[energy_name] = energy
        features[ratio_name] = float(energy / total_energy)

    mfcc = compute_mfcc(feature_power, mel_filterbank)
    for i, value in enumerate(mfcc, start=1):
        features[f"mfcc_{i}"] = float(value)

    if noise_profile is not None:
        raw_total_energy = float(np.sum(raw_power) + EPS)
        noise_total_energy = float(np.sum(noise_profile.mean_power) + EPS)
        features["snr_total_db"] = snr_db(raw_total_energy, noise_total_energy)
        for _energy_name, _ratio_name, snr_name, low_hz, high_hz in ENERGY_BANDS:
            if snr_name is None:
                continue
            raw_band = band_energy(freqs, raw_power, low_hz, high_hz)
            noise_band = band_energy(freqs, noise_profile.mean_power, low_hz, high_hz)
            features[snr_name] = snr_db(raw_band, noise_band)
        features["spectral_subtracted_energy"] = total_energy

    return features


def collect_profile_powers(wav_paths: list[Path], causal_filter: bool = True) -> tuple[np.ndarray, np.ndarray, int]:
    """노이즈 WAV 목록을 필터링/프레이밍해 평균 노이즈 프로파일 생성용 power matrix를 모읍니다."""
    if not wav_paths:
        raise FileNotFoundError("no WAV files were provided for noise profile generation")

    sos = design_bandpass_filter()
    window = signal.get_window(WINDOW_TYPE, FRAME_SIZE, fftbins=True).astype(np.float32)
    all_powers: list[np.ndarray] = []
    file_count = 0

    for wav_path in wav_paths:
        audio = read_wav_as_float32(wav_path)
        filtered = apply_bandpass(audio, sos, causal=causal_filter)
        file_count += 1
        for _start, frame in frame_signal(filtered):
            _freqs, power = compute_spectrum(frame, window)
            all_powers.append(power)

    if not all_powers:
        raise RuntimeError("noise profile generation produced no frames")

    powers = np.vstack(all_powers)
    return spectrum_freqs(), powers, file_count


def save_noise_profile(
    out_path: Path,
    wav_paths: list[Path],
    causal_filter: bool = True,
) -> NoiseProfile:
    """노이즈 WAV들로 평균 power와 noise floor를 계산해 압축 npz 프로파일로 저장합니다."""
    freqs, powers, file_count = collect_profile_powers(wav_paths, causal_filter=causal_filter)
    mean_power = np.mean(powers, axis=0)
    noise_floor_db = power_db(mean_power)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        freqs=freqs,
        mean_power=mean_power,
        noise_floor_db=noise_floor_db,
        sample_rate=np.array(SAMPLE_RATE),
        frame_size=np.array(FRAME_SIZE),
        hop_size=np.array(HOP_SIZE),
        fft_size=np.array(FFT_SIZE),
        window_type=np.array(WINDOW_TYPE),
        bpf_low_hz=np.array(BPF_LOW_HZ),
        bpf_high_hz=np.array(BPF_HIGH_HZ),
        bpf_order=np.array(BPF_ORDER),
        file_count=np.array(file_count),
        frame_count=np.array(powers.shape[0]),
        source_files=np.asarray([str(path) for path in wav_paths]),
        causal_filter=np.array(bool(causal_filter)),
    )
    return load_noise_profile(out_path)
