# -*- coding: utf-8 -*-
"""Rebuild the active 200 ms + MFCC-delta full56 STM32 model pipeline.

This is the current model path. The old 30-feature rebuild script was moved
to legacy because it can overwrite the full56 firmware assets with mismatched
30-feature outputs.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FULL56_SCRIPTS = PROJECT_ROOT / "full56_pipeline" / "scripts"
DEFAULT_DATASET = PROJECT_ROOT / "dataset_ics43434"


def run_step(name: str, command: list[str]) -> None:
    print(f"\n=== {name} ===")
    print(" ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the active full56 model and install its STM32 firmware assets."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--reuse-features", action="store_true")
    parser.add_argument("--skip-train", action="store_true", help="skip Keras model training/features step")
    parser.add_argument("--skip-export", action="store_true", help="skip TFLite/ST Edge AI candidate export")
    parser.add_argument("--skip-install", action="store_true", help="skip copying generated files into mouthnose")
    args = parser.parse_args(argv)

    dataset = args.dataset.resolve()
    if not dataset.is_dir():
        raise FileNotFoundError(f"dataset directory not found: {dataset}")

    train_cmd = [
        sys.executable,
        str(FULL56_SCRIPTS / "run_200ms_mfcc_delta_experiment.py"),
        "--dataset",
        str(dataset),
    ]
    if args.reuse_features:
        train_cmd.append("--reuse-features")

    if not args.skip_train:
        run_step("train full56 Keras model", train_cmd)

    if not args.skip_export:
        run_step(
            "export full56 STM32 candidate",
            [sys.executable, str(FULL56_SCRIPTS / "export_full56_stm32_candidate.py")],
        )

    if not args.skip_install:
        run_step(
            "install full56 assets into mouthnose",
            [sys.executable, str(FULL56_SCRIPTS / "install_full56_firmware_candidate.py")],
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
