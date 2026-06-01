# -*- coding: utf-8 -*-
"""Small ST Edge AI CLI resolver for the active full56 workflow.

The old 30-feature ``stm32_tinyml`` workspace used to provide this helper.
Keeping it here makes the active 200 ms + MFCC-delta pipeline self-contained,
so the legacy 30-feature workspace can be moved out of the project root.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil


def _version_key(path: Path) -> tuple[int, ...]:
    parts = path.name.replace("-", ".").split(".")
    return tuple(int(part) if part.isdigit() else -1 for part in parts)


def stedgeai_tool_candidates(tool: str | None = None) -> list[Path]:
    """Return likely ST Edge AI CLI paths, newest X-CUBE-AI pack first."""
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
    """Resolve the ST Edge AI CLI executable from an explicit path, PATH, or Cube repository."""
    for candidate in stedgeai_tool_candidates(tool):
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    searched = "\n".join(f"- {path}" for path in stedgeai_tool_candidates(tool))
    raise FileNotFoundError(
        "ST Edge AI CLI was not found. Install X-CUBE-AI/ST Edge AI Core, set "
        "STEDGEAI_EXE, or add the CLI folder to PATH.\n"
        f"Searched paths:\n{searched}"
    )
