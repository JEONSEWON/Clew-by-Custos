"""tests/test_dod.py — 1단계 DoD(Definition of Done) 자동 점검.

`python tasks.py dod`는 `pytest -k dod`로 본 파일의 테스트를 모은다.
탐지 로직 부재 단언은 test_no_label_leakage.py의 test_dod_detect_directory_empty /
test_dod_report_directory_empty에도 동일하게 있다.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


# 1. 정규 모델 스키마 + 직렬화/역직렬화 — 파일 존재 + 핵심 export
def test_dod_canonical_model_exists():
    model = ROOT / "src" / "clew" / "model.py"
    assert model.exists()
    text = model.read_text(encoding="utf-8")
    for sym in ("class Span", "class Trace", "class SpanNode", "SpanKind"):
        assert sym in text, f"model.py missing {sym!r}"


# 2. LangGraph 어댑터
def test_dod_langgraph_adapter_exists():
    adapter = ROOT / "src" / "clew" / "ingest" / "langgraph.py"
    assert adapter.exists()
    assert "otel_spans_to_trace" in adapter.read_text(encoding="utf-8")


# 3. 라벨셋 산출물 (build_set 실행 후)
def test_dod_labelset_artifacts_present():
    labels = ROOT / "eval" / "labels.jsonl"
    manifest = ROOT / "eval" / "set_manifest.json"
    traces_dir = ROOT / "eval" / "traces"
    assert labels.exists(), "run: python tasks.py generate-set"
    assert manifest.exists()
    n_traces = sum(1 for _ in traces_dir.glob("*.json"))
    assert n_traces == 80, f"expected 80 trace files, found {n_traces}"


# 4. CRITERIA_FROZEN 동결 + manifest sha256 일치
def test_dod_criteria_frozen_exists_and_pins_manifest():
    criteria = ROOT / "validation" / "CRITERIA_FROZEN.md"
    assert criteria.exists()
    text = criteria.read_text(encoding="utf-8")

    # 핵심 동결값 (CRITERIA_FROZEN.md 본문의 실제 표현과 정렬)
    for keyword in (
        "F1 ≥ 0.80",
        "false-positive rate ≤ 0.10",
        "F1 < 0.60",
        "Control FPR > 0.25",
        "N = 3회",
    ):
        assert keyword in text, f"CRITERIA_FROZEN.md missing {keyword!r}"

    # manifest sha256 일치 (라벨셋이 있을 때만)
    manifest = ROOT / "eval" / "set_manifest.json"
    if manifest.exists():
        actual = hashlib.sha256(manifest.read_bytes()).hexdigest()
        m = re.search(r"sha256[^`]*`([0-9a-f]{64})`", text)
        assert m is not None, "CRITERIA_FROZEN.md missing manifest sha256"
        assert m.group(1) == actual, (
            f"manifest sha256 drift — CRITERIA pins {m.group(1)} "
            f"but current manifest is {actual} (regen 또는 라벨셋 변조 의심)"
        )


# 5. 탐지 로직 없음(고의)
def test_dod_no_detect_or_report_code():
    detect_dir = ROOT / "src" / "clew" / "detect"
    report_dir = ROOT / "src" / "clew" / "report"
    assert list(detect_dir.glob("*.py")) == []
    assert list(report_dir.glob("*.py")) == []
