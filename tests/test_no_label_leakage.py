"""tests/test_no_label_leakage.py — Leakage guard (violations break the build).

(a) Directory separation is enforced by folder structure.
(b) Static scan via AST + source-literal check.
(c) Runtime probe (importing src.clew must not open label files).
(d) DoD assertion of emptiness in detect/ + report/ at stage 1.
(e) Guard self-verification (unit tests that catch intentional violations).
"""

from __future__ import annotations

import ast
import builtins
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
SRC_CLEW = ROOT / "src" / "clew"

# Literals whose presence in source is treated as leakage.
LEAK_LITERALS = (
    "eval/labels",
    "eval\\labels",
    "labels.jsonl",
    "labels.csv",
    "set_manifest.json",
)


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


# ----------------------------------------------------------------------
# (b) Static guard
# ----------------------------------------------------------------------

def test_src_clew_does_not_import_eval_or_labels():
    """AST: no module under src/clew imports eval.* or a labels module."""
    offenders: list[str] = []
    for f in _python_files(SRC_CLEW):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    parts = n.name.split(".")
                    if "eval" in parts or "labels" in n.name:
                        offenders.append(f"{f}: import {n.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                parts = mod.split(".")
                if "eval" in parts or "labels" in mod:
                    offenders.append(f"{f}: from {mod} import ...")
    assert not offenders, "\n".join(offenders)


def test_src_clew_does_not_reference_label_paths():
    """Source literals: fail if a label-path string appears in any .py file under src/clew."""
    offenders: list[str] = []
    for f in _python_files(SRC_CLEW):
        text = f.read_text(encoding="utf-8")
        for pat in LEAK_LITERALS:
            if pat in text:
                offenders.append(f"{f}: contains {pat!r}")
    assert not offenders, "\n".join(offenders)


def test_no_noqa_leak_whitelist_comment():
    """Ban guard-bypass channel (`# noqa-leak`)."""
    offenders: list[str] = []
    for f in _python_files(SRC_CLEW):
        if "noqa-leak" in f.read_text(encoding="utf-8"):
            offenders.append(str(f))
    assert not offenders, "noqa-leak whitelist found: " + ", ".join(offenders)


# ----------------------------------------------------------------------
# (c) Runtime probe
# ----------------------------------------------------------------------

def test_runtime_no_label_file_open():
    """The src.clew import path must not open label files."""
    opened: list[str] = []
    original_open = builtins.open

    def trace_open(path, *args, **kwargs):
        opened.append(str(path))
        return original_open(path, *args, **kwargs)

    with patch("builtins.open", trace_open):
        importlib.invalidate_caches()
        importlib.import_module("clew")
        importlib.import_module("clew.model")
        importlib.import_module("clew.ingest.langgraph")

    for p in opened:
        for pat in LEAK_LITERALS:
            assert pat not in p, f"src.clew runtime opened leaked path: {p}"


# ----------------------------------------------------------------------
# (d) DoD: stage-2 detection has exactly 4 modules / report/ is still absent
# ----------------------------------------------------------------------

def test_detect_directory_has_expected_modules():
    """src/clew/detect/ contains exactly 4 stage-2 modules (structural/semantic/cascade/__init__)."""
    detect_dir = SRC_CLEW / "detect"
    py_files = sorted(p.name for p in detect_dir.glob("*.py"))
    expected = ["__init__.py", "cascade.py", "semantic.py", "structural.py"]
    assert py_files == expected, f"detect/ expected {expected}, found: {py_files}"


def test_dod_report_directory_matches_stage3_scope():
    """Stage boundary guard — boundary refreshed by entering §10 (commit 85da2b3).
    Unrelated to frozen verification (leakage guard / eval). The .py files in report/ must exactly match the §10 planned modules.
    Adding any file outside the allowlist breaks this test.
    """
    expected = ["__init__.py", "_enrich.py", "_model.py", "json_report.py", "markdown.py"]
    report_dir = SRC_CLEW / "report"
    py_files = sorted(p.name for p in report_dir.glob("*.py"))
    assert py_files == expected, f"report/ expected {expected}, found: {py_files}"


def test_calibrate_does_not_reference_eval_set():
    """eval/calibrate.py must not contain the eval set (seed=42) path literal in its source.

    The dev set path (eval/dev/...) is allowed. Exactly the two literals 'eval/traces' and
    'eval/labels.jsonl' are blocked.
    """
    calibrate_path = ROOT / "eval" / "calibrate.py"
    if not calibrate_path.exists():
        pytest.skip("calibrate.py not yet created")
    text = calibrate_path.read_text(encoding="utf-8")
    scrubbed = text.replace("eval/dev/", "")
    assert "eval/traces" not in scrubbed, (
        "calibrate.py references eval set trace dir — must use dev set only"
    )
    assert "eval/labels.jsonl" not in scrubbed, (
        "calibrate.py references eval labels — must use dev labels only"
    )


def test_evaluate_does_not_reference_dev_set():
    """eval/evaluate.py must not contain the dev set (seed=7) path literal in its source.

    Symmetric guard: if evaluate reads the dev path, frozen bypass / leakage is possible. Block the 'eval/dev' literal.
    """
    evaluate_path = ROOT / "eval" / "evaluate.py"
    text = evaluate_path.read_text(encoding="utf-8")
    assert "eval/dev" not in text, (
        "evaluate.py references dev set — must read only the eval set (seed=42)"
    )
    assert "seed-7" not in text


# ----------------------------------------------------------------------
# (e) Guard self-verification — does it catch intentional violations?
# ----------------------------------------------------------------------

def test_guard_self_detects_import_violation(tmp_path):
    fake = tmp_path / "fake.py"
    fake.write_text("from eval import labels\n", encoding="utf-8")
    tree = ast.parse(fake.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if "eval" in mod.split(".") or "labels" in mod:
                violations.append(mod)
    assert violations, "AST guard failed to detect deliberate `from eval import labels`"


def test_guard_self_detects_literal_violation(tmp_path):
    fake = tmp_path / "fake.py"
    fake.write_text('path = "eval/labels.jsonl"\n', encoding="utf-8")
    text = fake.read_text(encoding="utf-8")
    assert any(p in text for p in LEAK_LITERALS), (
        "literal-scan guard failed to detect deliberate violation"
    )


def test_guard_self_detects_dotnotation_import(tmp_path):
    fake = tmp_path / "fake.py"
    fake.write_text("import eval.labels\n", encoding="utf-8")
    tree = ast.parse(fake.read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if "eval" in n.name.split(".") or "labels" in n.name:
                    found = True
    assert found, "AST guard failed to detect deliberate `import eval.labels`"
