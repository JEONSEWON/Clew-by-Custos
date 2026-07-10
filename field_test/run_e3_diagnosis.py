"""field_test/run_e3_diagnosis.py — Stage 15 E3 오탐 진단.

TRAIL 10개(GAIA 5 + SWE Bench 5)를 현재 동결 도구로 분석.
결과: field_test/E3_DIAGNOSIS.md
detect/·eval·φ/N/모델 전부 read-only.
"""
from __future__ import annotations

import statistics
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import hf_hub_download

_PHI   = 0.514345
_N     = 2
_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
_REV   = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
_CACHE = Path.home() / ".cache" / "clew" / "embeddings"
_HERE  = Path(__file__).parent
_OUT   = _HERE / "E3_DIAGNOSIS.md"

TRACES = [
    ("G1", "GAIA", "GAIA/0035f455b3ff2295167a844f04d85d34.json"),
    ("G2", "GAIA", "GAIA/0140b3f657eddf76ca82f72c49ac8e58.json"),
    ("G3", "GAIA", "GAIA/01c5727165fc43899b3b594b9bef5f19.json"),
    ("G4", "GAIA", "GAIA/cac8b6b2d84841d9a5177e399f0595b4.json"),
    ("G5", "GAIA", "GAIA/e7d5dd0d36db95a40a4fbe258edd0aba.json"),
    ("S1", "SWE Bench", "SWE Bench/0e6f7928953ab5a568bae640ce915cc3.json"),
    ("S2", "SWE Bench", "SWE Bench/72822db6e120878d916b515c2501246b.json"),
    ("S3", "SWE Bench", "SWE Bench/f12834d0194e0a3d406d1fe2e23d9fae.json"),
    ("S4", "SWE Bench", "SWE Bench/da17836ad8ecb77066313bdcbf25547a.json"),
    ("S5", "SWE Bench", "SWE Bench/2102eea2af6327834c8bd97b1488474c.json"),
]


def _run_one(label: str, split: str, hf_path: str, embedder):
    from clew.detect.cascade import cascade
    from clew.detect.semantic import cosine
    from clew.detect.structural import find_candidates
    from clew.ingest.otel_json import ingest_from_openinference_json

    t0 = time.time()
    local = Path(hf_hub_download(
        repo_id="PatronusAI/TRAIL",
        filename=hf_path,
        repo_type="dataset",
    ))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        trace = ingest_from_openinference_json(local)

    cr = cascade(trace, embedder, n=_N, phi=_PHI)

    waste_ids = set(cr.waste_span_ids)
    by_id = {s.span_id: s for s in trace.spans}
    pairs = find_candidates(trace, _N)

    fire_pairs: list[tuple] = []
    non_waste_cosines: list[float] = []
    for origin, candidate in pairs:
        sc = cosine(embedder.embed(origin.output_text), embedder.embed(candidate.output_text))
        if candidate.span_id in waste_ids:
            fire_pairs.append((origin, candidate, sc))
        else:
            non_waste_cosines.append(sc)

    elapsed = time.time() - t0
    print(f"  {label} [{split}] 스팬={len(trace.spans)} FIRE={len(fire_pairs)} 비낭비쌍={len(non_waste_cosines)} {elapsed:.1f}s")
    return {
        "label": label,
        "split": split,
        "hf_path": hf_path,
        "n_spans": len(trace.spans),
        "elapsed": elapsed,
        "fire_pairs": fire_pairs,
        "non_waste_cosines": non_waste_cosines,
    }


def _fmt_cosine_dist(cosines: list[float], phi: float) -> str:
    if not cosines:
        return "쌍 없음"
    above = sum(1 for c in cosines if c >= phi)
    med = statistics.median(cosines)
    return (
        f"쌍 수: {len(cosines)}  "
        f"min: {min(cosines):.4f}  median: {med:.4f}  max: {max(cosines):.4f}  "
        f"above-φ({phi}): {above}/{len(cosines)}"
    )


def _render_md(results: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []

    lines.append("# E3 오탐 진단 로그\n")
    lines.append(f"**실행일:** {now}  ")
    lines.append(f"**파라미터:** φ={_PHI}, N={_N}, model={_MODEL}\n")
    lines.append("---\n")
    lines.append("## 트레이스별 결과\n")

    total_fires = 0
    summary_rows: list[str] = []

    for r in results:
        label = r["label"]
        split = r["split"]
        hf_path = r["hf_path"]
        n_spans = r["n_spans"]
        elapsed = r["elapsed"]
        fire_pairs = r["fire_pairs"]
        non_waste = r["non_waste_cosines"]

        fname = hf_path.split("/")[-1]
        lines.append(f"### {label} — {split}/{fname}")
        lines.append(f"- 스팬 수(처리 후): {n_spans}개  처리 시간: {elapsed:.1f}s  FIRE: {len(fire_pairs)}건\n")

        if fire_pairs:
            for i, (orig, cand, sc) in enumerate(fire_pairs, 1):
                total_fires += 1
                lines.append(f"#### FIRE #{i} (누적 #{total_fires})")
                lines.append(f"- pattern: repeat_node  cosine: {sc:.4f}\n")
                lines.append(f"**Origin** `{orig.span_id}` `{orig.agent_or_node_id}` [{orig.span_kind}]")
                lines.append(f"- input_text: `{orig.input_text[:200]}`")
                lines.append(f"- output_text:\n```\n{orig.output_text[:500]}\n```\n")
                lines.append(f"**Candidate** `{cand.span_id}` `{cand.agent_or_node_id}` [{cand.span_kind}]")
                lines.append(f"- input_text: `{cand.input_text[:200]}`")
                lines.append(f"- output_text:\n```\n{cand.output_text[:500]}\n```\n")
                lines.append("**판정 (사람이 채움):**")
                lines.append("- [ ] 진짜낭비  [ ] 오탐  [ ] 애매")
                lines.append("- 메모:\n")
        else:
            lines.append("FIRE 없음\n")

        lines.append("**비낭비 쌍 코사인 분포**")
        lines.append(f"- {_fmt_cosine_dist(non_waste, _PHI)}\n")
        lines.append("---\n")

        summary_rows.append(f"| {label} | {split} | {n_spans} | {len(fire_pairs)} |")

    lines.append("## 집계 (자동)\n")
    lines.append("| 트레이스 | 타입 | 스팬 수 | FIRE 건수 |")
    lines.append("|---------|------|---------|----------|")
    lines.extend(summary_rows)
    lines.append(f"\n**총 FIRE: {total_fires}건**\n")

    lines.append("## 집계 (사람 판정 후 채움)\n")
    lines.append("| 분류 | 건수 |")
    lines.append("|------|------|")
    lines.append("| 진짜낭비 | |")
    lines.append("| 오탐 | |")
    lines.append("| 애매 | |")
    lines.append("| **오탐률** | |\n")

    lines.append("## 오탐 공통 원인 관찰 (사람이 채움)\n")
    lines.append("_데이터를 읽은 뒤 공통 패턴을 여기에 기록한다._\n")

    return "\n".join(lines)


def main() -> None:
    from clew.detect.semantic import Embedder

    print("Embedder 로드 중...")
    embedder = Embedder(model_name=_MODEL, revision=_REV, cache_dir=_CACHE)
    print("완료.\n")

    results = []
    for label, split, hf_path in TRACES:
        print(f"[{label}] {hf_path} 처리 중...")
        try:
            r = _run_one(label, split, hf_path, embedder)
            results.append(r)
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}")
            results.append({
                "label": label, "split": split, "hf_path": hf_path,
                "n_spans": 0, "elapsed": 0.0,
                "fire_pairs": [], "non_waste_cosines": [],
                "error": str(exc),
            })

    md = _render_md(results)
    _OUT.write_text(md, encoding="utf-8")
    print(f"\n→ {_OUT} 저장 완료")

    total = sum(len(r["fire_pairs"]) for r in results)
    print(f"총 FIRE: {total}건")
    if total < 5:
        print("⚠ FIRE 5건 미만 — 추가 배치 필요")


if __name__ == "__main__":
    main()
