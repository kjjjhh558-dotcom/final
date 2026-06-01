# -*- coding: utf-8 -*-
# 파일 설명: 저장된 WAV 파일에서 호흡 분류용 DSP/MFCC feature CSV를 생성하고 검증합니다.
#
# extract_features.py
#
# 목적:
#   collect_breath_dataset.py로 수집한 클래스별 WAV 클립에서 DSP 특징을 추출해
#   머신러닝 학습용 features.csv를 생성합니다.
#   현재 기본 구조는 dataset/<label>/<label>_NNN.wav입니다.
#   과거 세션 폴더 구조도 읽을 수 있지만, 새 데이터는 flat dataset 구조를 권장합니다.
#
# 기본 실행:
#   python extract_features.py
#
# split 규칙:
#   flat dataset 구조에서는 파일 번호가 5의 배수면 test, 나머지는 train으로 판단합니다.
#   예: nasal_inhale_005.wav -> test, nasal_inhale_006.wav -> train
#
# dataset 인식 상태 확인:
#   python extract_features.py --list-sessions dataset
#
# 검증만 실행:
#   python extract_features.py --verify-only features.csv
#
# 필요한 패키지:
#   pip install numpy scipy pandas
#
# 클래스 정책:
#   최종 학습 라벨은 nasal_inhale, nasal_exhale, mouth_inhale, mouth_exhale, noise입니다.
#   과거 수집 데이터에 no_breath/ 폴더가 남아 있어도 특징 추출 시 label을 noise로
#   자동 매핑합니다.
#
# 이식 참고:
#   STM32 CMSIS-DSP로 옮길 때 바꾸기 쉬운 값은 이 파일 상단의 상수로 모아두었습니다.
#   SAMPLE_RATE, FRAME_SIZE, HOP_SIZE, BPF_LOW_HZ, BPF_HIGH_HZ, ENERGY_BANDS,
#   NUM_MELS, NUM_MFCC를 먼저 확인하세요.

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import fftpack, signal
from scipy.io import wavfile

import dsp_features as dsp


# ---------------------------------------------------------------------------
# CMSIS-DSP 이식 시 우선 확인할 상수
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000
FRAME_SIZE = 1024
HOP_SIZE = 512
DEFAULT_DATASET_DIR = Path("dataset")
DEFAULT_FEATURES_CSV = Path("artifacts/features/features_all.csv")

BPF_LOW_HZ = 50.0
BPF_HIGH_HZ = 2500.0
BPF_ORDER = 4

ROLLOFF_RATIO = 0.85
EPS = 1.0e-12

FFT_SIZE = FRAME_SIZE
WINDOW_TYPE = "hann"

ENERGY_BANDS = (
    ("energy_50_300", "low_ratio", 50.0, 300.0),
    ("energy_300_800", "mid_ratio", 300.0, 800.0),
    ("energy_800_2000", "high_ratio", 800.0, 2000.0),
    ("energy_2000_4000", "very_high_ratio", 2000.0, 4000.0),
)

MFCC_FMIN_HZ = 50.0
MFCC_FMAX_HZ = 4000.0
NUM_MELS = 26
NUM_MFCC = 13

LABELS = (
    "nasal_inhale",
    "nasal_exhale",
    "mouth_inhale",
    "mouth_exhale",
    "noise",
)

SPLITS = ("train", "test")
TEST_EVERY_N = 5

LEGACY_LABEL_MAP = {
    "no_breath": "noise",
}

METADATA_COLUMNS = [
    "file",
    "path",
    "session",
    "label",
    "split",
    "frame_index",
    "start_sec",
    "end_sec",
]
FEATURE_COLUMNS = METADATA_COLUMNS + dsp.BASE_FEATURE_COLUMNS
NOISE_FEATURE_COLUMNS = list(dsp.NOISE_FEATURE_COLUMNS)


def output_feature_columns(noise_profile: dsp.NoiseProfile | None = None) -> list[str]:
    if noise_profile is None:
        return FEATURE_COLUMNS
    return FEATURE_COLUMNS + NOISE_FEATURE_COLUMNS


# 클래스 설명: 'WavRecord' 동작에 필요한 상태와 메서드를 묶는 클래스입니다.
@dataclass(frozen=True)
class WavRecord:
    wav_path: Path
    label: str
    split: str
    session: str
    feature_path: Path


# 함수 설명: 실행 환경이나 출력 형식을 현재 작업에 맞게 설정합니다.
def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


# 함수 설명: 'infer_split' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def infer_split(wav_path: Path) -> str:
    parent = wav_path.parent.parent.name
    if parent in SPLITS:
        return parent

    ordinal = wav_ordinal(wav_path)
    if ordinal > 0:
        return "test" if ordinal % TEST_EVERY_N == 0 else "train"

    return "legacy"


# 함수 설명: 'wav_ordinal' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def wav_ordinal(wav_path: Path) -> int:
    label = LEGACY_LABEL_MAP.get(wav_path.parent.name, wav_path.parent.name)
    if label not in LABELS:
        return -1

    prefix = f"{label}_"
    if not wav_path.stem.startswith(prefix):
        return -1

    number_text = wav_path.stem[len(prefix) :]
    return int(number_text) if number_text.isdigit() else -1


# 함수 설명: 'infer_session_name' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def infer_session_name(wav_path: Path, dataset_dir: Path) -> str:
    try:
        parts = wav_path.relative_to(dataset_dir).parts
    except ValueError:
        return dataset_dir.name

    known_labels = set(LABELS) | set(LEGACY_LABEL_MAP)

    if parts and parts[0] in SPLITS:
        return dataset_dir.name

    if len(parts) >= 3 and parts[0] not in SPLITS and parts[1] in SPLITS:
        return parts[0]

    if len(parts) >= 2 and parts[0] not in known_labels and parts[1] in known_labels:
        return parts[0]

    return dataset_dir.name


# 함수 설명: 'feature_relative_path' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def feature_relative_path(wav_path: Path, dataset_dir: Path, session: str) -> Path:
    relative_path = wav_path.relative_to(dataset_dir)
    if relative_path.parts and relative_path.parts[0] == session:
        return relative_path
    return Path(session) / relative_path


# 함수 설명: 'discover_wav_files' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def discover_wav_files(dataset_dir: Path, split: str = "all") -> list[WavRecord]:
    wav_files: list[WavRecord] = []

    for wav_path in sorted(dataset_dir.rglob("*.wav")):
        source_label = wav_path.parent.name
        label = LEGACY_LABEL_MAP.get(source_label, source_label)
        if label not in LABELS:
            continue

        split_name = infer_split(wav_path)
        if split != "all" and split_name != split:
            continue

        session = infer_session_name(wav_path, dataset_dir)
        wav_files.append(
            WavRecord(
                wav_path=wav_path,
                label=label,
                split=split_name,
                session=session,
                feature_path=feature_relative_path(wav_path, dataset_dir, session),
            )
        )

    return wav_files


# 함수 설명: 'discover_wav_files_from_sources' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def discover_wav_files_from_sources(dataset_dirs: list[Path], split: str = "all") -> tuple[list[WavRecord], list[Path]]:
    records: list[WavRecord] = []
    resolved_dirs: list[Path] = []
    seen_paths: set[Path] = set()

    for dataset_dir in dataset_dirs:
        resolved_dir = resolve_dataset_dir(dataset_dir)
        resolved_dirs.append(resolved_dir)

        for record in discover_wav_files(resolved_dir, split=split):
            resolved_wav = record.wav_path.resolve()
            if resolved_wav in seen_paths:
                continue
            seen_paths.add(resolved_wav)
            records.append(record)

    records.sort(key=lambda record: str(record.feature_path))
    return records, resolved_dirs


# 함수 설명: 'is_dataset_session_dir' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def is_dataset_session_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "metadata.csv").exists():
        return True
    return any((path / label).is_dir() for label in LABELS)


# 함수 설명: 파일 시스템이나 장치 목록을 훑어 필요한 항목을 수집합니다.
def list_dataset_sessions(dataset_root: Path) -> list[Path]:
    if not dataset_root.exists() or not dataset_root.is_dir():
        return []

    sessions = []
    if is_dataset_session_dir(dataset_root):
        sessions.append(dataset_root)

    for child in sorted(dataset_root.iterdir()):
        if is_dataset_session_dir(child):
            sessions.append(child)
    return sessions


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def format_available_sessions(dataset_root: Path) -> str:
    sessions = list_dataset_sessions(dataset_root)
    if not sessions:
        return f"No dataset sessions found under: {dataset_root}"

    lines = [f"Available sessions under {dataset_root}:"]
    for session in sessions:
        records = discover_wav_files(session)
        split_counts = Counter(record.split for record in records)
        split_text = ", ".join(
            f"{split}={split_counts[split]}" for split in ("train", "test", "legacy") if split_counts.get(split)
        )
        if not split_text:
            split_text = "no wav files"
        lines.append(f"  - {session.name} ({len(records)} wav files; {split_text})")
    return "\n".join(lines)


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def print_available_sessions(dataset_root: Path) -> None:
    print(format_available_sessions(dataset_root.resolve()))


# 함수 설명: 'resolve_dataset_dir' 단계의 입력을 처리해 다음 단계에 필요한 결과를 반환합니다.
def resolve_dataset_dir(dataset_dir: Path) -> Path:
    resolved = dataset_dir.resolve()
    if resolved.exists():
        if not resolved.is_dir():
            raise NotADirectoryError(f"not a directory: {resolved}")
        return resolved

    search_root = resolved.parent
    if not search_root.exists():
        search_root = Path("dataset").resolve()

    message = [f"dataset directory not found: {resolved}"]
    if search_root.exists():
        message.append(format_available_sessions(search_root))
    message.append("Tip: run `python extract_features.py --list-sessions dataset`")
    raise FileNotFoundError("\n".join(message))


# 아래 함수들은 dsp_features.py에 정식 구현이 있으므로 위임합니다.
pcm_to_float32 = dsp.pcm_to_float32
read_wav_as_float32 = dsp.read_wav_as_float32
design_bandpass_filter = dsp.design_bandpass_filter
apply_bandpass = dsp.apply_bandpass
hz_to_mel = dsp.hz_to_mel
mel_to_hz = dsp.mel_to_hz
build_mel_filterbank = dsp.build_mel_filterbank
frame_signal = dsp.frame_signal
zero_crossing_rate = dsp.zero_crossing_rate
compute_spectrum = dsp.compute_spectrum
band_energy = dsp.band_energy
compute_mfcc = dsp.compute_mfcc


# 함수 설명: 입력 데이터에서 필요한 수치, feature, 통계값을 계산합니다.
def extract_frame_features(
    frame: np.ndarray,
    frame_index: int,
    start_sample: int,
    record: WavRecord,
    label: str,
    split: str,
    window: np.ndarray,
    mel_filterbank: np.ndarray,
    noise_profile: dsp.NoiseProfile | None = None,
) -> dict[str, float | int | str]:
    feature_row: dict[str, float | int | str] = {
        "file": record.wav_path.name,
        "path": str(record.feature_path),
        "session": record.session,
        "label": label,
        "split": split,
        "frame_index": frame_index,
        "start_sec": start_sample / SAMPLE_RATE,
        "end_sec": (start_sample + FRAME_SIZE) / SAMPLE_RATE,
    }
    feature_row.update(dsp.extract_signal_features(frame, window, mel_filterbank, noise_profile=noise_profile))
    return feature_row


# 함수 설명: 입력 데이터에서 필요한 수치, feature, 통계값을 계산합니다.
def extract_wav_features(
    record: WavRecord,
    sos: np.ndarray,
    window: np.ndarray,
    mel_filterbank: np.ndarray,
    noise_profile: dsp.NoiseProfile | None = None,
) -> list[dict[str, float | int | str]]:
    audio = read_wav_as_float32(record.wav_path, SAMPLE_RATE)
    filtered = apply_bandpass(audio, sos)

    rows: list[dict[str, float | int | str]] = []
    for frame_index, (start_sample, frame) in enumerate(
        frame_signal(filtered, FRAME_SIZE, HOP_SIZE)
    ):
        rows.append(
            extract_frame_features(
                frame=frame,
                frame_index=frame_index,
                start_sample=start_sample,
                record=record,
                label=record.label,
                split=record.split,
                window=window,
                mel_filterbank=mel_filterbank,
                noise_profile=noise_profile,
            )
        )

    return rows


# 함수 설명: 입력 데이터에서 필요한 수치, feature, 통계값을 계산합니다.
def extract_dataset_features(
    dataset_dirs: list[Path],
    split: str = "all",
    noise_profile: dsp.NoiseProfile | None = None,
) -> tuple[pd.DataFrame, int, list[str], list[Path]]:
    wav_files, resolved_dirs = discover_wav_files_from_sources(dataset_dirs, split=split)

    if not wav_files:
        sources = ", ".join(str(path) for path in dataset_dirs)
        raise FileNotFoundError(f"no class WAV files found under: {sources} for split={split}")

    sos = design_bandpass_filter(SAMPLE_RATE)
    window = signal.get_window(WINDOW_TYPE, FRAME_SIZE, fftbins=True).astype(np.float32)
    mel_filterbank = build_mel_filterbank(
        SAMPLE_RATE,
        FFT_SIZE,
        NUM_MELS,
        MFCC_FMIN_HZ,
        MFCC_FMAX_HZ,
    )

    all_rows: list[dict[str, float | int | str]] = []
    processed_files = 0
    errors: list[str] = []

    for record in wav_files:
        try:
            rows = extract_wav_features(
                record=record,
                sos=sos,
                window=window,
                mel_filterbank=mel_filterbank,
                noise_profile=noise_profile,
            )
        except Exception as exc:
            errors.append(f"{record.wav_path}: {exc}")
            print(f"[WARN] skipped {record.wav_path}: {exc}", file=sys.stderr)
            continue

        if rows:
            all_rows.extend(rows)
            processed_files += 1

    if not all_rows:
        raise RuntimeError("no features were extracted")

    df = pd.DataFrame(all_rows)
    df = df.reindex(columns=output_feature_columns(noise_profile))
    return df, processed_files, errors, resolved_dirs


# 함수 설명: 계산된 결과나 데이터를 파일 또는 출력 장치에 저장합니다.
def save_features_csv(df: pd.DataFrame, out_path: Path) -> None:
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8")


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def print_frame_counts(df: pd.DataFrame) -> None:
    print()
    print("=== Frame Counts By Label ===")
    counts = df["label"].value_counts().sort_index()
    for label, count in counts.items():
        print(f"{label:<14}: {int(count)}")

    if "split" in df.columns:
        print()
        print("=== Frame Counts By Split ===")
        split_counts = df["split"].value_counts().sort_index()
        for split, count in split_counts.items():
            print(f"{split:<14}: {int(count)}")

    if "session" in df.columns:
        print()
        print("=== Frame Counts By Session ===")
        session_counts = df["session"].value_counts().sort_index()
        for session, count in session_counts.items():
            print(f"{session:<22}: {int(count)}")


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def print_feature_means(df: pd.DataFrame) -> None:
    summary_columns = [
        "rms",
        "zcr",
        "low_ratio",
        "mid_ratio",
        "high_ratio",
        "very_high_ratio",
    ]
    if "snr_total_db" in df.columns:
        summary_columns.append("snr_total_db")
    if "spectral_subtracted_energy" in df.columns:
        summary_columns.append("spectral_subtracted_energy")

    print()
    print("=== Mean RMS / ZCR / Band Ratios By Label ===")
    summary = df.groupby("label")[summary_columns].mean().sort_index()
    with pd.option_context("display.max_columns", None, "display.width", 140):
        print(summary.round(6).to_string())


# 함수 설명: 사용자에게 보여줄 텍스트나 요약 정보를 생성해 출력합니다.
def print_extraction_summary(
    df: pd.DataFrame,
    processed_files: int,
    errors: list[str],
    out_path: Path,
    source_dirs: list[Path],
    noise_profile: dsp.NoiseProfile | None = None,
) -> None:
    print()
    print("=== Extraction Summary ===")
    print(f"features_csv   : {out_path}")
    print("source_dirs    :")
    for source_dir in source_dirs:
        print(f"  - {source_dir}")
    print(f"noise_profile  : {noise_profile.path if noise_profile else 'off'}")
    print(f"processed_files: {processed_files}")
    print(f"total_frames   : {len(df)}")
    print(f"skipped_files  : {len(errors)}")
    print_frame_counts(df)
    print_feature_means(df)


# 함수 설명: 모델, feature, 산출물 상태를 기준값과 비교해 검증합니다.
def verify_features_csv(features_csv: Path) -> pd.DataFrame:
    if not features_csv.exists():
        raise FileNotFoundError(f"features CSV not found: {features_csv}")

    df = pd.read_csv(features_csv)
    if "split" not in df.columns:
        df["split"] = "legacy"
    if "session" not in df.columns:
        df["session"] = "unknown"

    missing_columns = [col for col in FEATURE_COLUMNS if col not in df.columns]
    if missing_columns:
        raise ValueError(f"missing feature columns: {missing_columns}")

    print_frame_counts(df)
    print_feature_means(df)
    return df


# 함수 설명: 명령행 옵션을 정의하고 사용자가 입력한 인자를 파싱합니다.
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract DSP and MFCC features from class-separated breath WAV clips."
    )
    parser.add_argument(
        "dataset_dirs",
        nargs="*",
        help=f"dataset root or legacy session dirs; default is {DEFAULT_DATASET_DIR}",
    )
    parser.add_argument("--out", default=str(DEFAULT_FEATURES_CSV), help="output features CSV path")
    parser.add_argument(
        "--split",
        choices=("all", "train", "test"),
        default="all",
        help="which collected split to extract from",
    )
    parser.add_argument(
        "--list-sessions",
        nargs="?",
        const="dataset",
        metavar="DATASET_ROOT",
        help="list available dataset sessions and exit; default root is ./dataset",
    )
    parser.add_argument(
        "--verify-only",
        metavar="FEATURES_CSV",
        help="only read an existing features.csv and print validation summaries",
    )
    parser.add_argument(
        "--noise-profile",
        metavar="PROFILE_NPZ",
        help="optional noise profile NPZ; applies spectrum power subtraction and adds SNR features",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="do not print RMS/ZCR/band-ratio validation summary after extraction",
    )

    args = parser.parse_args(argv)
    return args


# 함수 설명: 스크립트 진입점으로 인자를 읽고 전체 실행 흐름을 호출합니다.
def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        if args.list_sessions is not None:
            print_available_sessions(Path(args.list_sessions))
            return 0

        if args.verify_only:
            verify_features_csv(Path(args.verify_only))
            return 0

        dataset_dirs = [Path(value) for value in (args.dataset_dirs or [str(DEFAULT_DATASET_DIR)])]
        out_path = Path(args.out)
        noise_profile = dsp.load_noise_profile(Path(args.noise_profile)) if args.noise_profile else None

        df, processed_files, errors, source_dirs = extract_dataset_features(
            dataset_dirs,
            split=args.split,
            noise_profile=noise_profile,
        )
        save_features_csv(df, out_path)

        if args.no_summary:
            print()
            print("=== Extraction Summary ===")
            print(f"features_csv   : {out_path}")
            print("source_dirs    :")
            for source_dir in source_dirs:
                print(f"  - {source_dir}")
            print(f"noise_profile  : {noise_profile.path if noise_profile else 'off'}")
            print(f"processed_files: {processed_files}")
            print(f"total_frames   : {len(df)}")
            print(f"skipped_files  : {len(errors)}")
        else:
            print_extraction_summary(df, processed_files, errors, out_path, source_dirs, noise_profile)

        if errors:
            print()
            print("=== Skipped Files ===")
            for message in errors:
                print(message)

        return 0

    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("default")
        raise SystemExit(main())
