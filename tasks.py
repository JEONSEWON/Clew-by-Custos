"""tasks.py — cross-platform task runner.

사용: python tasks.py <command>

명령:
  install        의존성 설치 (uv 우선, 없으면 pip)
  test           전체 테스트
  check-leak     누수 가드 테스트만
  generate-set   라벨셋 생성 (seed=42, pairs-per-pattern=10)
  clean-set      라벨셋 산출물 삭제
  dod            DoD 자동 점검
  all            install -> generate-set -> test -> check-leak

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
        return run(["uv", "sync", "--extra", "adapter", "--extra", "dev"])
    return run([sys.executable, "-m", "pip", "install", "-e", ".[adapter,dev]"])


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
    "clean-set": cmd_clean_set,
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
