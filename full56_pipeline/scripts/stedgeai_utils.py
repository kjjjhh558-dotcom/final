# -*- coding: utf-8 -*-
"""ST Edge AI CLI 실행 파일을 찾기 위한 공통 유틸리티입니다.

명시 경로, 환경 변수, PATH, STM32Cube Repository의 X-CUBE-AI pack을 순서대로 탐색해 full56 export/install 스크립트가 같은 방식으로 도구를 찾게 합니다."""

from __future__ import annotations

import os
from pathlib import Path
import shutil


def _version_key(path: Path) -> tuple[int, ...]:
    """X-CUBE-AI pack 폴더명을 숫자 tuple로 바꿔 최신 버전을 먼저 정렬할 수 있게 합니다."""
    parts = path.name.replace("-", ".").split(".")
    return tuple(int(part) if part.isdigit() else -1 for part in parts)


def stedgeai_tool_candidates(tool: str | None = None) -> list[Path]:
    """명시 경로, 환경 변수, PATH, Cube Repository에서 ST Edge AI CLI 후보 경로를 중복 없이 모읍니다."""
    candidates: list[Path] = []

    for value in (tool, os.environ.get("STEDGEAI_EXE")):
        if value:
            candidates.append(Path(value))

    core_dir = os.environ.get("STEDGEAI_CORE_DIR")
    if core_dir:
        candidates.append(Path(core_dir) / "Utilities" / "windows" / "stedgeai.exe")
        candidates.append(Path(core_dir) / "stedgeai.exe")

    for name in ("stedgeai", "stedgeai.exe", "stm32ai", "stm32ai.exe"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))

    pack_root = Path.home() / "STM32Cube" / "Repository" / "Packs" / "STMicroelectronics" / "X-CUBE-AI"
    if pack_root.is_dir():
        for version_dir in sorted(pack_root.iterdir(), key=_version_key, reverse=True):
            candidates.append(version_dir / "Utilities" / "windows" / "stedgeai.exe")
            candidates.append(version_dir / "Utilities" / "windows" / "stm32ai.exe")

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        try:
            key = str(candidate.expanduser().resolve())
        except OSError:
            key = str(candidate.expanduser())
        if key not in seen:
            seen.add(key)
            unique.append(candidate.expanduser())
    return unique


def resolve_stedgeai_tool(tool: str | None = None) -> str:
    """실제로 존재하는 ST Edge AI CLI 경로를 선택하고 없으면 검색한 경로 목록과 함께 오류를 냅니다."""
    for candidate in stedgeai_tool_candidates(tool):
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    searched = "\n".join(f"- {path}" for path in stedgeai_tool_candidates(tool))
    raise FileNotFoundError(
        "ST Edge AI CLI was not found. Install X-CUBE-AI/ST Edge AI Core, set "
        "STEDGEAI_EXE, or add the CLI folder to PATH.\n"
        f"Searched paths:\n{searched}"
    )
