# -*- coding: utf-8 -*-
"""Run an isolated 200 ms + MFCC delta experiment.

This script does not modify the production TinyML pipeline. It writes all
features, models, and reports under the local full56_pipeline workspace.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import sys

import numpy as np
import pandas as pd
from scipy import fftpack, signal
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder


WORKSPACE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WORKSPACE_DIR.parent
SOURCE_FEATURES_DIR = PROJECT_ROOT / "scripts" / "features"
if str(SOURCE_FEATURES_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_FEATURES_DIR))

import extract_features as ef  # noqa: E402


SAMPLE_RATE = 16000
FRAME_SIZE = 3200          # 200 ms at 16 kHz
HOP_SIZE = 2400            # 25% overlap, 150 ms hop
FFT_SIZE = 4096
WINDOW_TYPE = "hann"
BPF_LOW_HZ = 50.0
BPF_HIGH_HZ = 2500.0
BPF_ORDER = 4
NUM_MELS = 26
NUM_MFCC = 13
MFCC_FMIN_HZ = 50.0
MFCC_FMAX_HZ = 4000.0
ROLLOFF_RATIO = 0.85
EPS = 1.0e-12

BREATH_LABELS = {"mouth_exhale", "mouth_inhale", "nasal_exhale", "nasal_inhale"}
LABELS = ["mouth_exhale", "mouth_inhale", "nasal_exhale", "nasal_inhale", "noise"]

ACTIVITY_SMOOTH_FRAMES = 3
ACTIVITY_THRESHOLD_RATIO = 0.50
ACTIVITY_FLOOR_PERCENTILE = 20.0
ACTIVITY_PEAK_PERCENTILE = 95.0
ACTIVITY_MIN_RUN_FRAMES = 2
ACTIVITY_MERGE_GAP_FRAMES = 1
ACTIVITY_PAD_FRAMES = 1
ABSOLUTE_RMS_FLOOR = 0.0015
DELTA_WIDTH = 2

METADATA_COLUMNS = [
    "file",
    "path",
    "session",
    "label",
    "source_label",
    "label_source",
    "breath_active",
    "activity_score",
    "split",
    "frame_index",
    "start_sec",
    "end_sec",
]

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
]
MFCC_COLUMNS = [f"mfcc_{i}" for i in range(1, NUM_MFCC + 1)]
DELTA_COLUMNS = [f"mfcc_delta_{i}" for i in range(1, NUM_MFCC + 1)]
DELTA2_COLUMNS = [f"mfcc_delta2_{i}" for i in range(1, NUM_MFCC + 1)]
FEATURE_COLUMNS = BASE_FEATURE_COLUMNS + MFCC_COLUMNS + DELTA_COLUMNS + DELTA2_COLUMNS
ALL_COLUMNS = METADATA_COLUMNS + FEATURE_COLUMNS
DROP_COLUMNS = set(METADATA_COLUMNS)

FEATURES_CSV = WORKSPACE_DIR / "features" / "features_200ms_mfcc_delta.csv"
TRAIN_FEATURES_CSV = WORKSPACE_DIR / "features" / "features_train_200ms_mfcc_delta.csv"
TEST_FEATURES_CSV = WORKSPACE_DIR / "features" / "features_test_200ms_mfcc_delta.csv"
RELABEL_SUMMARY_CSV = WORKSPACE_DIR / "features" / "features_relabel_summary_200ms.csv"
MODEL_PATH = WORKSPACE_DIR / "models" / "mlp_200ms_mfcc_delta.keras"
METRICS_JSON = WORKSPACE_DIR / "reports" / "mlp_200ms_mfcc_delta_metrics.json"
CONFUSION_CSV = WORKSPACE_DIR / "reports" / "mlp_200ms_mfcc_delta_confusion_matrix.csv"
FRAME_PREDICTIONS_CSV = WORKSPACE_DIR / "reports" / "mlp_200ms_mfcc_delta_frame_predictions.csv"
FILE_SUMMARY_CSV = WORKSPACE_DIR / "reports" / "mlp_200ms_mfcc_delta_file_summary.csv"
TRAINING_HISTORY_CSV = WORKSPACE_DIR / "reports" / "mlp_200ms_mfcc_delta_training_history.csv"


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def configure_tensorflow(seed: int):
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    import tensorflow as tf

    random.seed(seed)
    np.random.seed(seed)
    tf.random.set_seed(seed)
    return tf


def frame_signal(audio: np.ndarray) -> list[tuple[int, np.ndarray]]:
    if audio.size < FRAME_SIZE:
        padded = np.zeros(FRAME_SIZE, dtype=np.float32)
        padded[: audio.size] = audio
        return [(0, padded)]

    return [
        (start, audio[start : start + FRAME_SIZE])
        for start in range(0, audio.size - FRAME_SIZE + 1, HOP_SIZE)
    ]


def moving_average(values: np.ndarray, width: int) -> np.ndarray:
    if values.size == 0 or width <= 1:
        return values.astype(np.float64, copy=True)
    pad_left = width // 2
    pad_right = width - 1 - pad_left
    padded = np.pad(values.astype(np.float64), (pad_left, pad_right), mode="edge")
    kernel = np.ones(width, dtype=np.float64) / float(width)
    return np.convolve(padded, kernel, mode="valid")


def true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(mask):
        if bool(value) and start is None:
            start = index
        elif not bool(value) and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, int(mask.size)))
    return runs


def merge_runs(runs: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max_gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def build_activity_mask(frame_rms: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    if frame_rms.size == 0:
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=np.float64), 0.0

    smoothed = moving_average(frame_rms, ACTIVITY_SMOOTH_FRAMES)
    floor = float(np.percentile(smoothed, ACTIVITY_FLOOR_PERCENTILE))
    peak = float(np.percentile(smoothed, ACTIVITY_PEAK_PERCENTILE))
    dynamic_range = max(peak - floor, 0.0)
    threshold = floor + ACTIVITY_THRESHOLD_RATIO * dynamic_range
    if dynamic_range <= 1e-12:
        return np.zeros(frame_rms.size, dtype=bool), np.zeros(frame_rms.size, dtype=np.float64), threshold

    raw_mask = smoothed >= threshold
    runs = [run for run in true_runs(raw_mask) if (run[1] - run[0]) >= ACTIVITY_MIN_RUN_FRAMES]
    runs = merge_runs(runs, ACTIVITY_MERGE_GAP_FRAMES)

    active = np.zeros(frame_rms.size, dtype=bool)
    for start, end in runs:
        active[max(0, start - ACTIVITY_PAD_FRAMES) : min(frame_rms.size, end + ACTIVITY_PAD_FRAMES)] = True

    score = np.clip((smoothed - floor) / (dynamic_range + 1e-12), 0.0, None)
    return active, score, threshold


def zero_crossing_rate(frame: np.ndarray) -> float:
    signs = np.signbit(frame)
    return float(np.mean(signs[1:] != signs[:-1]))


def band_energy(freqs: np.ndarray, power: np.ndarray, low_hz: float, high_hz: float) -> float:
    mask = (freqs >= low_hz) & (freqs < high_hz)
    return float(np.sum(power[mask]))


def compute_mfcc(power: np.ndarray, mel_filterbank: np.ndarray) -> np.ndarray:
    mel_energy = mel_filterbank @ power
    log_mel_energy = np.log(mel_energy + EPS)
    return fftpack.dct(log_mel_energy, type=2, norm="ortho")[:NUM_MFCC].astype(np.float64)


def delta_matrix(values: np.ndarray, width: int = DELTA_WIDTH) -> np.ndarray:
    if values.size == 0:
        return values.copy()
    padded = np.pad(values, ((width, width), (0, 0)), mode="edge")
    denom = 2.0 * sum(i * i for i in range(1, width + 1))
    out = np.zeros_like(values, dtype=np.float64)
    for i in range(1, width + 1):
        out += i * (padded[width + i : width + i + len(values)] - padded[width - i : width - i + len(values)])
    return out / denom


def base_features(frame: np.ndarray, window: np.ndarray, mel_filterbank: np.ndarray) -> tuple[dict[str, float], np.ndarray]:
    rms = float(np.sqrt(np.mean(frame * frame) + EPS))
    log_rms = float(np.log(rms + EPS))
    zcr = zero_crossing_rate(frame)

    windowed = frame * window
    spectrum = np.fft.rfft(windowed, n=FFT_SIZE)
    power = (np.abs(spectrum) ** 2).astype(np.float64)
    freqs = np.fft.rfftfreq(FFT_SIZE, d=1.0 / SAMPLE_RATE)
    total_energy = float(np.sum(power))
    safe_total = total_energy + EPS

    centroid = float(np.sum(freqs * power) / safe_total)
    bandwidth = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * power) / safe_total))
    spectral_flatness = float(np.exp(np.mean(np.log(power + EPS))) / (np.mean(power) + EPS))
    cumulative = np.cumsum(power)
    rolloff_index = int(np.searchsorted(cumulative, ROLLOFF_RATIO * total_energy, side="left"))
    rolloff_index = min(rolloff_index, freqs.size - 1)
    rolloff = float(freqs[rolloff_index])
    dominant_freq = float(freqs[int(np.argmax(power))])

    energy_50_300 = band_energy(freqs, power, 50.0, 300.0)
    energy_300_800 = band_energy(freqs, power, 300.0, 800.0)
    energy_800_2000 = band_energy(freqs, power, 800.0, 2000.0)
    energy_2000_4000 = band_energy(freqs, power, 2000.0, 4000.0)
    mfcc = compute_mfcc(power, mel_filterbank)

    row = {
        "rms": rms,
        "log_rms": log_rms,
        "zcr": zcr,
        "spectral_centroid": centroid,
        "spectral_bandwidth": bandwidth,
        "spectral_flatness": spectral_flatness,
        "rolloff_85": rolloff,
        "dominant_freq": dominant_freq,
        "total_energy": total_energy,
        "energy_50_300": energy_50_300,
        "energy_300_800": energy_300_800,
        "energy_800_2000": energy_800_2000,
        "energy_2000_4000": energy_2000_4000,
        "low_ratio": float(energy_50_300 / safe_total),
        "mid_ratio": float(energy_300_800 / safe_total),
        "high_ratio": float(energy_800_2000 / safe_total),
        "very_high_ratio": float(energy_2000_4000 / safe_total),
    }
    for idx, value in enumerate(mfcc, start=1):
        row[f"mfcc_{idx}"] = float(value)
    return row, mfcc


def extract_one_file(record, sos: np.ndarray, window: np.ndarray, mel_filterbank: np.ndarray) -> list[dict[str, object]]:
    audio = ef.read_wav_as_float32(record.wav_path, SAMPLE_RATE)
    filtered = signal.sosfilt(sos, audio).astype(np.float32)
    framed = frame_signal(filtered)
    frame_rms = np.asarray([np.sqrt(np.mean(frame * frame) + EPS) for _start, frame in framed], dtype=np.float64)

    source_label = record.label
    if source_label in BREATH_LABELS:
        active_mask, activity_score, _threshold = build_activity_mask(frame_rms)
    else:
        active_mask = np.zeros(len(framed), dtype=bool)
        activity_score = np.zeros(len(framed), dtype=np.float64)

    base_rows: list[dict[str, object]] = []
    mfcc_rows: list[np.ndarray] = []
    for frame_index, (start_sample, frame) in enumerate(framed):
        rms_val = float(frame_rms[frame_index])
        breath_active = bool(active_mask[frame_index] and rms_val >= ABSOLUTE_RMS_FLOOR) if source_label in BREATH_LABELS else False
        if source_label in BREATH_LABELS:
            label = source_label if breath_active else "noise"
            label_source = "active_breath" if breath_active else "inactive_to_noise"
        else:
            label = source_label
            label_source = "source_noise"

        row, mfcc = base_features(frame, window, mel_filterbank)
        row.update(
            {
                "file": record.wav_path.name,
                "path": str(record.feature_path),
                "session": record.session,
                "label": label,
                "source_label": source_label,
                "label_source": label_source,
                "breath_active": int(breath_active),
                "activity_score": float(activity_score[frame_index]) if frame_index < len(activity_score) else 0.0,
                "split": record.split,
                "frame_index": frame_index,
                "start_sec": float(start_sample / SAMPLE_RATE),
                "end_sec": float((start_sample + FRAME_SIZE) / SAMPLE_RATE),
            }
        )
        base_rows.append(row)
        mfcc_rows.append(mfcc)

    mfcc_matrix = np.vstack(mfcc_rows) if mfcc_rows else np.zeros((0, NUM_MFCC), dtype=np.float64)
    delta = delta_matrix(mfcc_matrix, DELTA_WIDTH)
    delta2 = delta_matrix(delta, DELTA_WIDTH)
    for row, d1, d2 in zip(base_rows, delta, delta2):
        for idx, value in enumerate(d1, start=1):
            row[f"mfcc_delta_{idx}"] = float(value)
        for idx, value in enumerate(d2, start=1):
            row[f"mfcc_delta2_{idx}"] = float(value)
    return base_rows


def build_relabel_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for source_label, group in df.groupby("source_label", sort=True):
        source_frames = int(len(group))
        rows.append(
            {
                "source_label": source_label,
                "source_files": int(group["path"].nunique()),
                "source_frames": source_frames,
                "active_breath_frames": int(((group["source_label"] == group["label"]) & (group["breath_active"].astype(int) == 1)).sum()),
                "relabeled_noise_frames": int((group["label_source"] == "inactive_to_noise").sum()),
                "original_noise_frames": int((group["label_source"] == "source_noise").sum()),
                "active_ratio": float(((group["source_label"] == group["label"]) & (group["breath_active"].astype(int) == 1)).sum() / source_frames) if source_frames else 0.0,
            }
        )
    return pd.DataFrame(rows)


def extract_dataset(dataset_dir: Path) -> pd.DataFrame:
    records, _resolved_dirs = ef.discover_wav_files_from_sources([dataset_dir], split="all")
    if not records:
        raise FileNotFoundError(f"no wav files found under {dataset_dir}")

    sos = ef.design_bandpass_filter(SAMPLE_RATE, BPF_LOW_HZ, BPF_HIGH_HZ, BPF_ORDER)
    window = signal.get_window(WINDOW_TYPE, FRAME_SIZE, fftbins=True).astype(np.float32)
    mel_filterbank = ef.build_mel_filterbank(SAMPLE_RATE, FFT_SIZE, NUM_MELS, MFCC_FMIN_HZ, MFCC_FMAX_HZ)

    rows: list[dict[str, object]] = []
    for index, record in enumerate(records, start=1):
        rows.extend(extract_one_file(record, sos, window, mel_filterbank))
        if index % 100 == 0:
            print(f"processed {index}/{len(records)} files", flush=True)

    df = pd.DataFrame(rows)
    return df.reindex(columns=ALL_COLUMNS)


def prepare_feature_matrix(df: pd.DataFrame, feature_columns: list[str]) -> np.ndarray:
    x = df[feature_columns].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return x.to_numpy(dtype=np.float32)


def class_weight_dict(y_encoded: np.ndarray, labels: list[str], noise_weight_multiplier: float) -> dict[int, float]:
    classes, counts = np.unique(y_encoded, return_counts=True)
    total = float(len(y_encoded))
    n_classes = float(len(classes))
    weights = {int(cls): float(total / (n_classes * count)) for cls, count in zip(classes, counts)}
    if "noise" in labels:
        noise_index = labels.index("noise")
        if noise_index in weights:
            weights[noise_index] *= float(noise_weight_multiplier)
    return weights


def parse_hidden_layers(text: str) -> list[int]:
    values = [int(part.strip()) for part in text.split(",") if part.strip()]
    if not values or any(value <= 0 for value in values):
        raise ValueError("--hidden-layers must be a comma-separated list of positive integers")
    return values


def build_model(tf, feature_count: int, hidden_layers: list[int], learning_rate: float):
    inputs = tf.keras.Input(shape=(feature_count,), name="features")
    normalizer = tf.keras.layers.Normalization(axis=-1, name="feature_normalization")
    x = normalizer(inputs)
    for index, units in enumerate(hidden_layers, start=1):
        x = tf.keras.layers.Dense(units, activation="relu", name=f"dense_{index}")(x)
    outputs = tf.keras.layers.Dense(len(LABELS), activation="softmax", name="class_probabilities")(x)
    model = tf.keras.Model(inputs=inputs, outputs=outputs, name="breath_200ms_mfcc_delta_mlp")
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model, normalizer


def aggregate_file_predictions(frame_predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for file_id, group in frame_predictions.groupby("path", sort=True):
        true_label = group["source_label"].mode().iloc[0]
        vote_group = group
        if true_label != "noise":
            active_group = group[group["breath_active"].astype(int) > 0]
            if not active_group.empty:
                vote_group = active_group
        pred_counts = vote_group["pred_label"].value_counts()
        pred_label = pred_counts.index[0]
        rows.append(
            {
                "file_id": file_id,
                "file": group["file"].iloc[0],
                "label": true_label,
                "frame_label_mode": group["label"].mode().iloc[0],
                "pred_label": pred_label,
                "correct": bool(true_label == pred_label),
                "frames": int(len(group)),
                "vote_frames": int(len(vote_group)),
                "active_frames": int(group["breath_active"].astype(int).sum()),
                "vote_ratio": float(pred_counts.iloc[0] / len(vote_group)),
                "mean_confidence": float(vote_group["pred_confidence"].mean()),
            }
        )
    return pd.DataFrame(rows)


def route(label: str) -> str:
    if label.startswith("mouth_"):
        return "mouth"
    if label.startswith("nasal_"):
        return "nasal"
    if label == "noise":
        return "noise"
    return "other"


def phase(label: str) -> str:
    if label.endswith("_exhale"):
        return "exhale"
    if label.endswith("_inhale"):
        return "inhale"
    if label == "noise":
        return "noise"
    return "other"


def route_phase_metrics(frame_predictions: pd.DataFrame, file_predictions: pd.DataFrame) -> dict[str, float]:
    active = frame_predictions[
        frame_predictions["source_label"].isin(BREATH_LABELS)
        & (frame_predictions["breath_active"].astype(int) > 0)
    ].copy()
    active["true_route"] = active["source_label"].map(route)
    active["pred_route"] = active["pred_label"].map(route)
    active["true_phase"] = active["source_label"].map(phase)
    active["pred_phase"] = active["pred_label"].map(phase)
    pred_breath = active[active["pred_label"].isin(BREATH_LABELS)].copy()

    breath_files = file_predictions[file_predictions["label"].isin(BREATH_LABELS)].copy()
    breath_files["true_route"] = breath_files["label"].map(route)
    breath_files["pred_route"] = breath_files["pred_label"].map(route)
    breath_files["true_phase"] = breath_files["label"].map(phase)
    breath_files["pred_phase"] = breath_files["pred_label"].map(phase)
    file_pred_breath = breath_files[breath_files["pred_label"].isin(BREATH_LABELS)].copy()

    def mean_bool(series: pd.Series) -> float:
        return float(series.mean()) if len(series) else 0.0

    return {
        "active_frame_route_accuracy": mean_bool(active["true_route"] == active["pred_route"]),
        "active_frame_phase_accuracy": mean_bool(active["true_phase"] == active["pred_phase"]),
        "active_frame_pred_breath_rate": float(len(pred_breath) / len(active)) if len(active) else 0.0,
        "active_frame_route_accuracy_when_pred_breath": mean_bool(pred_breath["true_route"] == pred_breath["pred_route"]),
        "active_frame_phase_accuracy_when_pred_breath": mean_bool(pred_breath["true_phase"] == pred_breath["pred_phase"]),
        "file_breath_route_accuracy": mean_bool(breath_files["true_route"] == breath_files["pred_route"]),
        "file_breath_phase_accuracy": mean_bool(breath_files["true_phase"] == breath_files["pred_phase"]),
        "file_breath_pred_breath_rate": float(len(file_pred_breath) / len(breath_files)) if len(breath_files) else 0.0,
        "file_breath_route_accuracy_when_pred_breath": mean_bool(file_pred_breath["true_route"] == file_pred_breath["pred_route"]),
        "file_breath_phase_accuracy_when_pred_breath": mean_bool(file_pred_breath["true_phase"] == file_pred_breath["pred_phase"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "dataset_ics43434")
    parser.add_argument("--hidden-layers", default="16,8")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--validation-split", type=float, default=0.15)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--noise-weight-multiplier", type=float, default=2.0)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--reuse-features", action="store_true")
    args = parser.parse_args(argv)

    configure_stdio()
    for path in [FEATURES_CSV.parent, MODEL_PATH.parent, METRICS_JSON.parent]:
        path.mkdir(parents=True, exist_ok=True)

    dataset_dir = args.dataset.resolve()
    if args.reuse_features and FEATURES_CSV.exists():
        print(f"Loading existing features: {FEATURES_CSV}")
        df = pd.read_csv(FEATURES_CSV)
    else:
        print("Extracting 200 ms + MFCC delta features...")
        df = extract_dataset(dataset_dir)
        df.to_csv(FEATURES_CSV, index=False, encoding="utf-8")
        df[df["split"] == "train"].to_csv(TRAIN_FEATURES_CSV, index=False, encoding="utf-8")
        df[df["split"] == "test"].to_csv(TEST_FEATURES_CSV, index=False, encoding="utf-8")
        build_relabel_summary(df).to_csv(RELABEL_SUMMARY_CSV, index=False, encoding="utf-8")

    train_df = df[df["split"] == "train"].copy()
    test_df = df[df["split"] == "test"].copy()
    feature_columns = [column for column in df.columns if column not in DROP_COLUMNS]
    x_train = prepare_feature_matrix(train_df, feature_columns)
    x_test = prepare_feature_matrix(test_df, feature_columns)

    encoder = LabelEncoder()
    encoder.fit(LABELS)
    labels = list(encoder.classes_)
    y_train = encoder.transform(train_df["label"].astype(str))
    y_test = encoder.transform(test_df["label"].astype(str))

    tf = configure_tensorflow(args.random_state)
    hidden_layers = parse_hidden_layers(args.hidden_layers)
    model, normalizer = build_model(tf, len(feature_columns), hidden_layers, args.learning_rate)
    normalizer.adapt(x_train)
    class_weights = class_weight_dict(y_train, labels, args.noise_weight_multiplier)
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=args.patience,
            restore_best_weights=True,
        )
    ]
    history = model.fit(
        x_train,
        y_train,
        epochs=args.epochs,
        batch_size=args.batch_size,
        validation_split=args.validation_split,
        class_weight=class_weights,
        callbacks=callbacks,
        verbose=2,
    )

    probabilities = model.predict(x_test, verbose=0)
    pred_encoded = np.argmax(probabilities, axis=1)
    pred_labels = encoder.inverse_transform(pred_encoded)

    frame_predictions = test_df.copy()
    frame_predictions["pred_label"] = pred_labels
    frame_predictions["pred_confidence"] = np.max(probabilities, axis=1)
    frame_predictions["correct"] = frame_predictions["label"].astype(str) == frame_predictions["pred_label"].astype(str)
    file_predictions = aggregate_file_predictions(frame_predictions)

    frame_accuracy = float(accuracy_score(frame_predictions["label"], frame_predictions["pred_label"]))
    file_accuracy = float(accuracy_score(file_predictions["label"], file_predictions["pred_label"]))
    report = classification_report(
        frame_predictions["label"],
        frame_predictions["pred_label"],
        labels=labels,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(frame_predictions["label"], frame_predictions["pred_label"], labels=labels)
    cm_df = pd.DataFrame(cm, index=labels, columns=labels)

    model.save(MODEL_PATH, include_optimizer=False)
    pd.DataFrame(history.history).assign(epoch=lambda x: np.arange(1, len(x) + 1)).to_csv(
        TRAINING_HISTORY_CSV, index=False, encoding="utf-8"
    )
    frame_predictions.to_csv(FRAME_PREDICTIONS_CSV, index=False, encoding="utf-8")
    file_predictions.to_csv(FILE_SUMMARY_CSV, index=False, encoding="utf-8")
    cm_df.to_csv(CONFUSION_CSV, encoding="utf-8", index_label="actual")

    metrics = {
        "experiment": "200ms_mfcc_delta",
        "dataset": str(dataset_dir),
        "feature_source": "causal_sosfilt_200ms_mfcc_delta",
        "sample_rate": SAMPLE_RATE,
        "frame_size": FRAME_SIZE,
        "hop_size": HOP_SIZE,
        "frame_ms": 1000.0 * FRAME_SIZE / SAMPLE_RATE,
        "hop_ms": 1000.0 * HOP_SIZE / SAMPLE_RATE,
        "overlap_ratio": 1.0 - (HOP_SIZE / FRAME_SIZE),
        "fft_size": FFT_SIZE,
        "bpf_low_hz": BPF_LOW_HZ,
        "bpf_high_hz": BPF_HIGH_HZ,
        "bpf_order": BPF_ORDER,
        "num_mels": NUM_MELS,
        "num_mfcc": NUM_MFCC,
        "delta_width": DELTA_WIDTH,
        "feature_columns": feature_columns,
        "feature_count": len(feature_columns),
        "train_frames": int(len(train_df)),
        "test_frames": int(len(test_df)),
        "train_files": int(train_df["path"].nunique()),
        "test_files": int(test_df["path"].nunique()),
        "labels": labels,
        "hidden_layers": hidden_layers,
        "param_count": int(model.count_params()),
        "hyperparameters": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "validation_split": args.validation_split,
            "patience": args.patience,
            "random_state": args.random_state,
            "noise_weight_multiplier": args.noise_weight_multiplier,
            "class_weight": {str(key): float(value) for key, value in class_weights.items()},
        },
        "best_epoch": int(np.argmin(history.history.get("val_loss", [0.0])) + 1),
        "frame_accuracy": frame_accuracy,
        "file_accuracy": file_accuracy,
        "classification_report": report,
        "route_phase_metrics": route_phase_metrics(frame_predictions, file_predictions),
        "outputs": {
            "features_csv": str(FEATURES_CSV),
            "model_path": str(MODEL_PATH),
            "metrics_json": str(METRICS_JSON),
            "confusion_csv": str(CONFUSION_CSV),
            "frame_predictions_csv": str(FRAME_PREDICTIONS_CSV),
            "file_summary_csv": str(FILE_SUMMARY_CSV),
            "relabel_summary_csv": str(RELABEL_SUMMARY_CSV),
        },
    }
    METRICS_JSON.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=== 200 ms + MFCC Delta Experiment Summary ===")
    print(f"features      : {FEATURES_CSV}")
    print(f"model         : {MODEL_PATH}")
    print(f"metrics       : {METRICS_JSON}")
    print(f"feature_count : {len(feature_columns)}")
    print(f"train/test    : {len(train_df)} / {len(test_df)} frames")
    print(f"frame acc     : {frame_accuracy * 100.0:.2f}%")
    print(f"file acc      : {file_accuracy * 100.0:.2f}%")
    print(f"best epoch    : {metrics['best_epoch']}")
    print("route/phase   :")
    for key, value in metrics["route_phase_metrics"].items():
        print(f"  {key}: {value * 100.0:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
