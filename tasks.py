"""tasks.py — cross-platform task runner.

사용: python tasks.py <command>

명령:
  install            의존성 설치 (uv 우선, 없으면 pip)
  test               전체 테스트
  check-leak         누수 가드 테스트만
  generate-set       라벨셋 생성 (seed=42, pairs-per-pattern=10)
  generate-dev-set   2단계 dev 라벨셋 생성 (seed=7, pairs-per-pattern=10)
  calibrate          dev set으로 φ·N·모델 결정 + CALIBRATION_LOG.md 갱신
  evaluate           평가 set 단 1회 측정 + EVAL_RUNS.md 추가 (CRITERIA 동결 필수)
  clean-set          라벨셋 산출물 삭제
  clean-dev-set      dev 라벨셋 산출물 삭제
  dod                DoD 자동 점검
  all                install -> generate-set -> test -> check-leak

Windows에 make 기본 없음. 이 스크립트가 그 자리를 대체.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def has_uv() -> bool:
    return shutil.which("uv") is not None


def run(cmd: list[str]) -> int:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def _py_run(args_after: list[str]) -> list[str]:
    if has_uv():
        return ["uv", "run", *args_after]
    return [sys.executable, *args_after]


def cmd_install(_args: argparse.Namespace) -> int:
    if has_uv():
        return run(["uv", "sync", "--extra", "adapter", "--extra", "detect", "--extra", "dev"])
    return run([sys.executable, "-m", "pip", "install", "-e", ".[adapter,detect,dev]"])


def cmd_test(_args: argparse.Namespace) -> int:
    return run(_py_run(["-m", "pytest", "-v"]))


def cmd_check_leak(_args: argparse.Namespace) -> int:
    return run(_py_run(["-m", "pytest", "tests/test_no_label_leakage.py", "-v"]))


def cmd_generate_set(_args: argparse.Namespace) -> int:
    return run(
        _py_run(
            [
                "-m",
                "eval.generators.build_set",
                "--seed",
                "42",
                "--pairs-per-pattern",
                "10",
                "--out-dir",
                "eval/",
            ]
        )
    )


def cmd_clean_set(_args: argparse.Namespace) -> int:
    traces_dir = ROOT / "eval" / "traces"
    if traces_dir.exists():
        for p in traces_dir.iterdir():
            if p.is_file() and p.name != ".gitkeep":
                p.unlink()
    for f in (ROOT / "eval" / "labels.jsonl", ROOT / "eval" / "set_manifest.json"):
        if f.exists():
            f.unlink()
    print("cleaned eval/traces/, labels.jsonl, set_manifest.json")
    return 0


def cmd_generate_dev_set(_args: argparse.Namespace) -> int:
    return run(
        _py_run(
            [
                "-m",
                "eval.generators.build_set",
                "--seed",
                "7",
                "--pairs-per-pattern",
                "10",
                "--out-dir",
                "eval/dev/seed-7",
            ]
        )
    )


def cmd_calibrate(_args: argparse.Namespace) -> int:
    return run(_py_run(["-m", "eval.calibrate"]))


def cmd_evaluate(_args: argparse.Namespace) -> int:
    return run(_py_run(["-m", "eval.evaluate"]))


def cmd_clean_dev_set(_args: argparse.Namespace) -> int:
    dev_dir = ROOT / "eval" / "dev"
    if dev_dir.exists():
        import shutil as _shutil
        _shutil.rmtree(dev_dir)
        print(f"cleaned {dev_dir}")
    else:
        print("no dev set to clean")
    return 0


def cmd_dod(_args: argparse.Namespace) -> int:
    return run(_py_run(["-m", "pytest", "tests/", "-v", "-k", "dod"]))


def cmd_all(args: argparse.Namespace) -> int:
    for fn in (cmd_install, cmd_generate_set, cmd_test, cmd_check_leak):
        rc = fn(args)
        if rc != 0:
            return rc
    return 0


COMMANDS = {
    "install": cmd_install,
    "test": cmd_test,
    "check-leak": cmd_check_leak,
    "generate-set": cmd_generate_set,
    "generate-dev-set": cmd_generate_dev_set,
    "calibrate": cmd_calibrate,
    "evaluate": cmd_evaluate,
    "clean-set": cmd_clean_set,
    "clean-dev-set": cmd_clean_dev_set,
    "dod": cmd_dod,
    "all": cmd_all,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Clew task runner")
    parser.add_argument("command", choices=list(COMMANDS))
    args = parser.parse_args()
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
