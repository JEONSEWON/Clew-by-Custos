"""eval/evaluate.py — 2단계 평가 진입점 (현재 스텁).

src/clew 의 어떤 모듈도 절대 import 못하는 *유일한 라벨 reader*. 누수 가드의 디렉터리
분리 원칙(plan §5)을 명시한다. 실제 평가 로직은 2단계에서 채운다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_labels(path: Path = Path("eval/labels.jsonl")) -> dict[str, dict[str, Any]]:
    """라벨 JSONL 로드 — trace_id → 라벨 레코드."""
    out: dict[str, dict[str, Any]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out[rec["trace_id"]] = rec
    return out


def evaluate(detector_outputs, labels, criteria_frozen):
    raise NotImplementedError("Stage 2 — detection logic not yet built.")
