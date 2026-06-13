"""build_set.py — paired 검증 라벨셋 빌더 (CLI).

각 패턴마다 `pairs_per_pattern` 쌍을 생성:
  - positive 트레이스 1개 + 길이·토폴로지 매칭 clean(negative) 트레이스 1개.

산출:
  eval/traces/<trace_id>.json   — 트레이스 본문 (라벨 hint 일절 없음)
  eval/labels.jsonl             — 한 줄 한 라벨 (trace_id로 join)
  eval/set_manifest.json        — seed/카운트/페어 목록/길이 분포

결정론: 같은 seed → 바이트 단위 동일한 산출물. manifest sha256은 CRITERIA_FROZEN.md에
박혀, 동결 시점 라벨셋과 평가 시점 라벨셋의 일치를 보장한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

from eval.generators.patterns import PATTERNS


def _stable_seed(parent_seed: int, *parts: str) -> int:
    h = hashlib.sha256()
    h.update(str(parent_seed).encode("utf-8"))
    for p in parts:
        h.update(b"\x00")
        h.update(p.encode("utf-8"))
    return int.from_bytes(h.digest()[:8], "big")


def build_set(*, seed: int, pairs_per_pattern: int, out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    traces_dir = out_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    labels_path = out_dir / "labels.jsonl"
    manifest_path = out_dir / "set_manifest.json"

    pattern_names = list(PATTERNS.keys())

    counter = 0
    labels_lines: list[str] = []
    pairs: list[dict[str, Any]] = []
    lengths: list[int] = []
    pattern_counts: dict[str, int] = {p: 0 for p in pattern_names}
    written_trace_files: list[str] = []

    for pattern in pattern_names:
        pos_fn, clean_fn = PATTERNS[pattern]
        for i in range(pairs_per_pattern):
            counter += 1
            pos_tid = f"t-{counter:04d}"
            pos_seed = _stable_seed(seed, pattern, str(i), "p")
            pos = pos_fn(trace_id=pos_tid, seed=pos_seed)

            counter += 1
            clean_tid = f"t-{counter:04d}"
            clean_seed = _stable_seed(seed, pattern, str(i), "c")
            clean = clean_fn(trace_id=clean_tid, seed=clean_seed)

            if len(pos.trace.spans) != len(clean.trace.spans):
                raise RuntimeError(
                    f"paired length mismatch (pattern={pattern}, pair={i})"
                )

            (traces_dir / f"{pos_tid}.json").write_text(
                pos.trace.model_dump_json(), encoding="utf-8"
            )
            (traces_dir / f"{clean_tid}.json").write_text(
                clean.trace.model_dump_json(), encoding="utf-8"
            )
            written_trace_files.extend([f"{pos_tid}.json", f"{clean_tid}.json"])

            labels_lines.append(
                json.dumps(
                    {
                        "trace_id": pos_tid,
                        "class": "positive",
                        "pattern": pattern,
                        "waste_span_ids": pos.waste_span_ids,
                    },
                    ensure_ascii=False,
                )
            )
            labels_lines.append(
                json.dumps(
                    {
                        "trace_id": clean_tid,
                        "class": "negative",
                        "pattern": None,
                        "waste_span_ids": [],
                    },
                    ensure_ascii=False,
                )
            )

            pairs.append(
                {
                    "positive_trace_id": pos_tid,
                    "negative_trace_id": clean_tid,
                    "pattern": pattern,
                    "length": len(pos.trace.spans),
                }
            )
            lengths.extend([len(pos.trace.spans), len(clean.trace.spans)])
            pattern_counts[pattern] += 1

    labels_path.write_text("\n".join(labels_lines) + "\n", encoding="utf-8")

    # 산출물 sha — 트레이스 본문 변경이 manifest sha에 반영되도록.
    labels_sha = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    combined = hashlib.sha256()
    for fname in sorted(written_trace_files):
        combined.update(fname.encode("utf-8"))
        combined.update(b"\x00")
        combined.update((traces_dir / fname).read_bytes())
        combined.update(b"\x00")
    traces_sha = combined.hexdigest()

    total_pos = sum(pattern_counts.values())
    manifest = {
        "seed": seed,
        "schema_version": "1.0",
        "pairs_per_pattern": pairs_per_pattern,
        "counts": {
            "positive": total_pos,
            "negative": total_pos,
            "total": total_pos * 2,
        },
        "pattern_distribution": pattern_counts,
        "length_distribution": {
            "min": min(lengths),
            "max": max(lengths),
            "mean": round(statistics.fmean(lengths), 3),
        },
        "artifacts_sha256": {
            "labels": labels_sha,
            "traces_combined": traces_sha,
        },
        "pairs": pairs,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    return {
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "trace_files": written_trace_files,
        "labels_path": labels_path,
        "manifest_path": manifest_path,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Build paired waste-detection label set")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pairs-per-pattern", type=int, default=10)
    p.add_argument("--out-dir", type=Path, default=Path("eval"))
    args = p.parse_args()
    info = build_set(
        seed=args.seed,
        pairs_per_pattern=args.pairs_per_pattern,
        out_dir=args.out_dir,
    )
    print(f"counts:           {info['manifest']['counts']}")
    print(f"pattern_distrib:  {info['manifest']['pattern_distribution']}")
    print(f"length_distrib:   {info['manifest']['length_distribution']}")
    print(f"manifest sha256:  {info['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
