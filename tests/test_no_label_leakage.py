"""tests/test_no_label_leakage.py — 누수 가드 (어기면 빌드 깨짐).

(a) 디렉터리 분리는 폴더 구조로 보장.
(b) AST + 본문 리터럴 정적 스캔.
(c) 런타임 프로브 (src.clew import 시 라벨 파일을 열지 않는다).
(d) detect/ + report/ 1단계에서 비어있음 단언 (DoD).
(e) 가드 자체-검증 (의도적 위반을 잡는지 단위 테스트).
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

# 본문에 등장하면 누수로 간주하는 리터럴.
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
# (b) 정적 가드
# ----------------------------------------------------------------------

def test_src_clew_does_not_import_eval_or_labels():
    """AST: src/clew 의 어떤 모듈도 eval.* 또는 labels 모듈을 import하지 않음."""
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
    """본문 리터럴: src/clew 의 .py 파일에 라벨 경로 문자열 등장 시 fail."""
    offenders: list[str] = []
    for f in _python_files(SRC_CLEW):
        text = f.read_text(encoding="utf-8")
        for pat in LEAK_LITERALS:
            if pat in text:
                offenders.append(f"{f}: contains {pat!r}")
    assert not offenders, "\n".join(offenders)


def test_no_noqa_leak_whitelist_comment():
    """가드 우회 통로(`# noqa-leak`) 도입 금지."""
    offenders: list[str] = []
    for f in _python_files(SRC_CLEW):
        if "noqa-leak" in f.read_text(encoding="utf-8"):
            offenders.append(str(f))
    assert not offenders, "noqa-leak whitelist found: " + ", ".join(offenders)


# ----------------------------------------------------------------------
# (c) 런타임 프로브
# ----------------------------------------------------------------------

def test_runtime_no_label_file_open():
    """src.clew 임포트 패스에서 라벨 파일을 열지 않음."""
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
# (d) DoD: 1단계 탐지/리포트 코드 없음
# ----------------------------------------------------------------------

def test_dod_detect_directory_empty():
    """src/clew/detect/ 에 .py 파일 없음 — 1단계 탐지 로직 금지."""
    detect_dir = SRC_CLEW / "detect"
    py_files = list(detect_dir.glob("*.py"))
    assert py_files == [], f"detect/ should be empty (stage 1), found: {py_files}"


def test_dod_report_directory_empty():
    """src/clew/report/ 에 .py 파일 없음 — 1단계 리포트 로직 금지."""
    report_dir = SRC_CLEW / "report"
    py_files = list(report_dir.glob("*.py"))
    assert py_files == [], f"report/ should be empty (stage 1), found: {py_files}"


# ----------------------------------------------------------------------
# (e) 가드 자체-검증 — 의도적 위반을 잡는지
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
