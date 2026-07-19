"""tests/test_dod.py — stage 1 DoD (Definition of Done) automated check.

`python tasks.py dod` collects this file's tests via `pytest -k dod`.
The assertion that detection logic is absent also appears identically in
test_no_label_leakage.py's test_dod_detect_directory_empty /
test_dod_report_directory_empty.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


# 1. Canonical model schema + serialization/deserialization — file exists + core exports
def test_dod_canonical_model_exists():
    model = ROOT / "src" / "clew" / "model.py"
    assert model.exists()
    text = model.read_text(encoding="utf-8")
    for sym in ("class Span", "class Trace", "class SpanNode", "SpanKind"):
        assert sym in text, f"model.py missing {sym!r}"


# 2. LangGraph adapter
def test_dod_langgraph_adapter_exists():
    adapter = ROOT / "src" / "clew" / "ingest" / "langgraph.py"
    assert adapter.exists()
    assert "otel_spans_to_trace" in adapter.read_text(encoding="utf-8")


# 3. Labelset artifacts (after build_set run)
def test_dod_labelset_artifacts_present():
    labels = ROOT / "eval" / "labels.jsonl"
    manifest = ROOT / "eval" / "set_manifest.json"
    traces_dir = ROOT / "eval" / "traces"
    if not labels.exists():
        pytest.skip("labelset not generated — run: python tasks.py generate-set")
    assert labels.exists(), "run: python tasks.py generate-set"
    assert manifest.exists()
    n_traces = sum(1 for _ in traces_dir.glob("*.json"))
    assert n_traces == 80, f"expected 80 trace files, found {n_traces}"


# 4. CRITERIA_FROZEN frozen + manifest sha256 match
def test_dod_criteria_frozen_exists_and_pins_manifest():
    criteria = ROOT / "validation" / "CRITERIA_FROZEN.md"
    assert criteria.exists()
    text = criteria.read_text(encoding="utf-8")

    # Core frozen values (aligned with the actual wording in CRITERIA_FROZEN.md)
    for keyword in (
        "F1 ≥ 0.80",
        "false-positive rate ≤ 0.10",
        "F1 < 0.60",
        "Control FPR > 0.25",
        "N = 3회",
    ):
        assert keyword in text, f"CRITERIA_FROZEN.md missing {keyword!r}"

    # manifest sha256 match (only when labelset exists)
    manifest = ROOT / "eval" / "set_manifest.json"
    if manifest.exists():
        actual = hashlib.sha256(manifest.read_bytes()).hexdigest()
        m = re.search(r"sha256[^`]*`([0-9a-f]{64})`", text)
        assert m is not None, "CRITERIA_FROZEN.md missing manifest sha256"
        assert m.group(1) == actual, (
            f"manifest sha256 drift — CRITERIA pins {m.group(1)} "
            f"but current manifest is {actual} (suspect regen or labelset tampering)"
        )


# 5. Detect module exists; report modules match §10 plan exactly (stage boundary guard — boundary updated upon entering §10)
def test_dod_detect_and_report_modules_match_stage3_scope():
    detect_dir = ROOT / "src" / "clew" / "detect"
    report_dir = ROOT / "src" / "clew" / "report"
    detect_files = sorted(p.name for p in detect_dir.glob("*.py"))
    assert detect_files == ["__init__.py", "cascade.py", "semantic.py", "structural.py"]
    expected_report = ["__init__.py", "_enrich.py", "_model.py", "json_report.py", "markdown.py"]
    assert sorted(p.name for p in report_dir.glob("*.py")) == expected_report
