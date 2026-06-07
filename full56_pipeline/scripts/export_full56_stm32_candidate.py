# -*- coding: utf-8 -*-
"""full56 Keras 모델을 TFLite와 ST Edge AI 후보 산출물로 내보냅니다.

production 펌웨어는 수정하지 않고 full56_pipeline/stm32_candidate 아래에 후보 모델, TFLite 평가 결과, ST Edge AI 생성 로그와 요약 JSON을 남깁니다."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = WORKSPACE_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import stedgeai_utils  # noqa: E402

FULL56_MODEL = WORKSPACE_DIR / "models" / "mlp_200ms_mfcc_delta.keras"
FULL56_FEATURES = WORKSPACE_DIR / "features" / "features_200ms_mfcc_delta.csv"
FULL56_METRICS = WORKSPACE_DIR / "reports" / "mlp_200ms_mfcc_delta_metrics.json"
OUT_DIR = WORKSPACE_DIR / "stm32_candidate" / "full56"
MODEL_DIR = OUT_DIR / "model"
STEDGEAI_RUNS_DIR = OUT_DIR / "stedgeai_runs"
REPORTS_DIR = OUT_DIR / "reports"


def configure_stdio() -> None:
    """후보 export 로그가 Windows 콘솔에서 UTF-8로 보이도록 설정합니다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def read_json(path: Path) -> dict:
    """metrics JSON을 UTF-8로 읽어 dict로 반환합니다."""
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict) -> None:
    """후보 생성 요약 JSON을 보기 좋은 UTF-8 형식으로 저장합니다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def timestamp() -> str:
    """ST Edge AI 실행 폴더와 로그 이름에 사용할 현재 시각 문자열을 만듭니다."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def export_tflite(tf, keras_model: Path, tflite_out: Path) -> None:
    """Keras 모델을 로드해 float TFLite 모델 파일로 변환합니다."""
    if not keras_model.exists():
        raise FileNotFoundError(f"missing Keras model: {keras_model}")
    model = tf.keras.models.load_model(keras_model)
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite_out.parent.mkdir(parents=True, exist_ok=True)
    tflite_out.write_bytes(converter.convert())


def evaluate_tflite(tf, tflite_path: Path, features_csv: Path, feature_columns: list[str]) -> dict:
    """생성된 TFLite를 테스트 feature CSV로 실행해 프레임 정확도와 예측 CSV를 만듭니다."""
    df = pd.read_csv(features_csv)
    test_df = df[df["split"] == "test"].copy()
    if test_df.empty:
        raise ValueError("features CSV has no test rows")
    x_test = (
        test_df[feature_columns]
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .to_numpy(dtype=np.float32)
    )
    labels = ["mouth_exhale", "mouth_inhale", "nasal_exhale", "nasal_inhale", "noise"]
    interpreter = tf.lite.Interpreter(model_content=tflite_path.read_bytes())
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]

    predictions: list[str] = []
    for row in x_test:
        interpreter.set_tensor(input_detail["index"], row.reshape(input_detail["shape"]).astype(input_detail["dtype"]))
        interpreter.invoke()
        output = interpreter.get_tensor(output_detail["index"]).reshape(-1)
        predictions.append(labels[int(np.argmax(output))])

    result = test_df[["file", "path", "label", "source_label", "breath_active"]].copy()
    result["pred_label"] = predictions
    result["correct"] = result["label"].astype(str) == result["pred_label"].astype(str)
    frame_accuracy = float(accuracy_score(result["label"], result["pred_label"]))
    pred_path = REPORTS_DIR / "full56_tflite_frame_predictions.csv"
    pred_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(pred_path, index=False, encoding="utf-8")

    return {
        "frame_accuracy": frame_accuracy,
        "input_shape": [int(v) for v in input_detail["shape"].tolist()],
        "output_shape": [int(v) for v in output_detail["shape"].tolist()],
        "input_dtype": str(input_detail["dtype"]),
        "output_dtype": str(output_detail["dtype"]),
        "predictions_csv": str(pred_path),
    }


def copy_output_tree(source: Path, destination: Path) -> None:
    """임시 ST Edge AI output 폴더를 후보 보관 폴더로 재귀 복사합니다."""
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def run_stedgeai(tflite_path: Path, network_name: str, direct_paths: bool = False) -> dict:
    """TFLite 후보를 ST Edge AI CLI로 C 코드 생성하고 stdout/stderr와 manifest를 남깁니다."""
    run_id = timestamp()
    run_dir = STEDGEAI_RUNS_DIR / f"run_{run_id}"
    run_output_dir = run_dir / "stedgeai_output"
    run_dir.mkdir(parents=True, exist_ok=True)

    temp_root = Path(tempfile.gettempdir()) / "stm32_breath_full56_stedgeai" / run_id
    temp_model_dir = temp_root / "model"
    temp_output_dir = temp_root / "output"
    temp_workspace_dir = temp_root / "workspace"
    for path in (temp_model_dir, temp_output_dir, temp_workspace_dir):
        path.mkdir(parents=True, exist_ok=True)

    tool = stedgeai_utils.resolve_stedgeai_tool(None)
    if direct_paths:
        model_for_tool = tflite_path.resolve()
        output_for_tool = run_output_dir
        workspace_for_tool = run_dir / "workspace"
    else:
        model_for_tool = temp_model_dir / tflite_path.name
        shutil.copy2(tflite_path, model_for_tool)
        output_for_tool = temp_output_dir
        workspace_for_tool = temp_workspace_dir

    command = [
        tool,
        "generate",
        "-m",
        str(model_for_tool),
        "--target",
        "stm32f4",
        "--type",
        "tflite",
        "--name",
        network_name,
        "--output",
        str(output_for_tool),
        "--workspace",
        str(workspace_for_tool),
        "--verbosity",
        "1",
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    (run_dir / "stedgeai_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (run_dir / "stedgeai_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if not direct_paths:
        copy_output_tree(temp_output_dir, run_output_dir)

    manifest = {
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "stedgeai_output_dir": str(run_output_dir),
        "network_name": network_name,
        "command": command,
        "command_text": subprocess.list2cmdline(command),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "generated_files": sorted(
            str(path.relative_to(run_output_dir)).replace("\\", "/")
            for path in run_output_dir.rglob("*")
            if path.is_file()
        ) if run_output_dir.exists() else [],
    }
    write_json(run_dir / "stedgeai_full56_summary.json", manifest)
    write_json(OUT_DIR / "latest_stedgeai_full56_summary.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    """TFLite 변환, TFLite 평가, 선택적 ST Edge AI 생성, 후보 요약 저장을 실행합니다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--keras-model", type=Path, default=FULL56_MODEL)
    parser.add_argument("--features-csv", type=Path, default=FULL56_FEATURES)
    parser.add_argument("--metrics-json", type=Path, default=FULL56_METRICS)
    parser.add_argument("--network-name", default="breath_mlp_full56")
    parser.add_argument("--skip-stedgeai", action="store_true")
    args = parser.parse_args(argv)

    configure_stdio()
    for path in (MODEL_DIR, REPORTS_DIR, STEDGEAI_RUNS_DIR):
        path.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    import tensorflow as tf

    metrics = read_json(args.metrics_json)
    feature_columns = list(metrics["feature_columns"])
    tflite_path = MODEL_DIR / "mlp_200ms_mfcc_delta_full56.tflite"
    export_tflite(tf, args.keras_model, tflite_path)
    tflite_eval = evaluate_tflite(tf, tflite_path, args.features_csv, feature_columns)

    stedgeai = None
    if not args.skip_stedgeai:
        stedgeai = run_stedgeai(tflite_path, args.network_name)
        if stedgeai["status"] != "ok":
            print(stedgeai.get("stderr_tail") or stedgeai.get("stdout_tail"), file=sys.stderr)
            return int(stedgeai.get("returncode", 1))

    summary = {
        "status": "ok",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_keras": str(args.keras_model),
        "source_features_csv": str(args.features_csv),
        "source_metrics_json": str(args.metrics_json),
        "feature_count": len(feature_columns),
        "feature_columns": feature_columns,
        "tflite_path": str(tflite_path),
        "tflite_size_bytes": int(tflite_path.stat().st_size),
        "tflite_eval": tflite_eval,
        "stedgeai": stedgeai,
        "migration_note": (
            "Model-side export only. Firmware DSP still needs 200ms frame, "
            "4096 FFT, and sequence MFCC delta/delta-delta implementation."
        ),
    }
    write_json(OUT_DIR / "full56_stm32_candidate_summary.json", summary)

    print()
    print("=== Full56 STM32 Candidate Export ===")
    print(f"tflite       : {tflite_path}")
    print(f"tflite size  : {summary['tflite_size_bytes']} bytes")
    print(f"input shape  : {tflite_eval['input_shape']}")
    print(f"frame acc    : {tflite_eval['frame_accuracy'] * 100.0:.2f}%")
    if stedgeai:
        print(f"stedgeai     : {stedgeai['status']} {stedgeai['stedgeai_output_dir']}")
    print(f"summary      : {OUT_DIR / 'full56_stm32_candidate_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
