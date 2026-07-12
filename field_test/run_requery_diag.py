"""field_test/run_requery_diag.py — Stage 18 requery 오탐 진단.

TRAIL 80개(HF API 동적 열거)에서 requery 성격 FIRE(tool kind + input 정규화 동일)만
추출. 판정란·집계는 비워 둔다 — 판정은 사람이 원문으로.

detect/·eval·φ/N/모델 전부 read-only.
_extract_target은 참고 표기 전용. 자동 판정·집계에 절대 불사용.
"""
from __future__ import annotations

import re
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
_OUT   = _HERE / "REQUERY_DIAGNOSIS.md"
_LIMIT = 80

_BAD_FILES = {
    "72822db6e120878d916b515c2501246b",  # duplicate span_id ParseError
}


def _list_trail_traces(limit: int = _LIMIT) -> list[tuple[str, str, str]]:
    """HF API로 TRAIL 파일 목록 열거. (label, split, hf_path) 리스트 반환."""
    try:
        from huggingface_hub import list_repo_tree
        items = list(list_repo_tree(
            "PatronusAI/TRAIL", repo_type="dataset", expand=True, recursive=True
        ))
        paths_with_size: list[tuple[str, int]] = [
            (item.path, getattr(item, "size", 0))
            for item in items
            if hasattr(item, "path")
            and item.path.endswith(".json")
            and ("GAIA/" in item.path or "SWE Bench/" in item.path)
            and not any(b in item.path for b in _BAD_FILES)
        ]
        paths_with_size.sort(key=lambda x: x[1], reverse=True)
        paths = [p for p, _ in paths_with_size]
    except Exception:
        from huggingface_hub import list_repo_files
        paths = [
            p for p in list_repo_files("PatronusAI/TRAIL", repo_type="dataset")
            if p.endswith(".json")
            and ("GAIA/" in p or "SWE Bench/" in p)
            and not any(b in p for b in _BAD_FILES)
        ]

    result: list[tuple[str, str, str]] = []
    g_idx = s_idx = 0
    for p in paths[:limit]:
        if p.startswith("GAIA/"):
            g_idx += 1
            label = f"G{g_idx}"
            split = "GAIA"
        else:
            s_idx += 1
            label = f"S{s_idx}"
            split = "SWE Bench"
        result.append((label, split, p))
    return result


def _extract_target(output: str) -> str:
    """output에서 'Address: ...' 라인 추출. 없으면 앞 80자.

    TRAIL 전용 형식 — 오버핏 방지를 위해 참고용 표기에만 사용.
    자동으로 대상 동일성을 판정하거나 집계에 쓰지 않는다.
    """
    m = re.search(r"^Address: (.+)$", output, re.MULTILINE)
    return m.group(1).strip() if m else output[:80].replace("\n", " ")


def _run_one(label: str, split: str, hf_path: str, embedder) -> dict:
    from clew.detect.cascade import cascade
    from clew.detect.semantic import cosine
    from clew.detect.structural import (  # type: ignore[attr-defined]
        _nearest_agent_ancestor_id,
        find_candidates,
    )
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
    requery_pairs: list[dict] = []

    for origin, candidate in pairs:
        if candidate.span_id not in waste_ids:
            continue
        if origin.span_kind != "tool":
            # requery 성격(tool+동일input)만 수집. agent/llm 반복은 제외.
            continue
        # structural에서 이미 입력 정규화 동일이 보장된 상태로 여기까지 옴.
        sc = cosine(embedder.embed(origin.output_text), embedder.embed(candidate.output_text))
        agent_id = _nearest_agent_ancestor_id(origin.parent_span_id, by_id)
        agent_name = by_id[agent_id].agent_or_node_id if agent_id else "None"
        # _extract_target: 참고 표기 전용. 판정·집계 불사용.
        target_o = _extract_target(origin.output_text)
        target_c = _extract_target(candidate.output_text)
        requery_pairs.append({
            "origin": origin,
            "candidate": candidate,
            "cosine": sc,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "target_o": target_o,
            "target_c": target_c,
        })

    elapsed = time.time() - t0
    print(
        f"  {label} [{split}] 스팬={len(trace.spans)} "
        f"requery FIRE={len(requery_pairs)} {elapsed:.1f}s"
    )
    return {
        "label": label,
        "split": split,
        "hf_path": hf_path,
        "n_spans": len(trace.spans),
        "elapsed": elapsed,
        "requery_pairs": requery_pairs,
    }


def _render_md(results: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    total = sum(len(r["requery_pairs"]) for r in results)

    lines.append("# REQUERY_DIAGNOSIS — requery 오탐 진단 (Stage 18)\n")
    lines.append(f"**실행일:** {now}  ")
    lines.append(f"**파라미터:** φ={_PHI}, N={_N}, model={_MODEL}  ")
    lines.append(f"**트레이스 수:** {len(results)}개  **requery FIRE 총수:** {total}건  ")
    lines.append("**필터:** tool kind + 입력 정규화 동일 (structural 레이어 보장)  ")
    lines.append("**_extract_target:** TRAIL 전용 참고용 — 판정·집계에 불사용\n")
    lines.append("---\n")
    lines.append("## requery FIRE 상세\n")

    seq = 0
    for r in results:
        if not r["requery_pairs"]:
            continue
        label = r["label"]
        split = r["split"]
        fname = r["hf_path"].split("/")[-1]
        for item in r["requery_pairs"]:
            seq += 1
            orig = item["origin"]
            cand = item["candidate"]
            sc = item["cosine"]
            agent_name = item["agent_name"]
            target_o = item["target_o"]
            target_c = item["target_c"]

            lines.append(f"### REQUERY #{seq} — {label}/{split}/{fname}")
            lines.append(
                f"- cosine: {sc:.4f}  "
                f"tool: {orig.agent_or_node_id}  "
                f"부모AGENT: {agent_name}\n"
            )

            # Origin — output 먼저, 자동추출 대상은 맨 뒤
            lines.append(f"**Origin** `{orig.span_id}`")
            lines.append(f"- input: `{orig.input_text[:300]}`")
            lines.append(f"- 정규화 input: `{orig.input_text.strip().casefold()[:200]}`")
            lines.append(f"- output (전문, 최대 800자):\n```\n{orig.output_text[:800]}\n```")
            lines.append(f"- 참고(자동추출, TRAIL 전용): `{target_o}`\n")

            # Candidate — 동일 순서
            lines.append(f"**Candidate** `{cand.span_id}`")
            lines.append(f"- input: `{cand.input_text[:300]}`")
            lines.append(f"- 정규화 input: `{cand.input_text.strip().casefold()[:200]}`")
            lines.append(f"- output (전문, 최대 800자):\n```\n{cand.output_text[:800]}\n```")
            lines.append(f"- 참고(자동추출, TRAIL 전용): `{target_c}`\n")

            # 판정란 (비워둠)
            lines.append("**판정 (사람이 채움):**")
            lines.append("- 대상: [ ] 같은대상  [ ] 다른대상  [ ] 애매")
            lines.append("- 낭비: [ ] 진짜낭비  [ ] 정당한탐색  [ ] 애매")
            lines.append("- 메모:\n")

            # origin 선택 관찰란
            lines.append("**origin 선택 관찰 (사람이 채움):**")
            lines.append("- candidate들끼리 대상이 같은데 origin만 다른가? [ ] 해당  [ ] 해당없음")
            lines.append("- 메모:\n")

            lines.append("---\n")

    # 집계 (자동 집계 없음 — 판정 후 사람이 채움)
    lines.append("## 집계 (사람 판정 후 채움)\n")
    lines.append(f"**requery FIRE 총수: {total}건 (tool+동일input, 게이트 통과)**\n")

    lines.append("### 교차표: 대상 동일성 × 진짜 낭비\n")
    lines.append("|              | 진짜낭비 | 정당한탐색 | 애매 |")
    lines.append("|--------------|---------|-----------|-----|")
    lines.append("| 같은 대상     |         |           |     |")
    lines.append("| 다른 대상     |         |           |     |")
    lines.append("| 애매         |         |           |     |\n")

    lines.append("### 확증편향 반례란")
    lines.append("- 대상 같은데 정당한탐색: ")
    lines.append("- 대상 다른데 진짜낭비:  \n")

    lines.append("### origin 선택 약점 관찰")
    lines.append('- "origin 선택 관찰: 해당" 건수: ')
    lines.append("- 대표 사례(G3 유형 재발 여부): \n")

    lines.append("### 코사인 분포 관찰")
    lines.append("- 대상 동일 군 cosine: ")
    lines.append("- 대상 다른 군 cosine: ")
    lines.append("- 신호 후보: \n")

    lines.append("## 결론 (사람이 채움)\n")
    lines.append("- '대상 동일성이 진짜 낭비를 가르는 신호인가': ")
    lines.append("- 다음 단계: \n")

    return "\n".join(lines)


def main() -> None:
    from clew.detect.semantic import Embedder

    print("Embedder 로드 중...")
    embedder = Embedder(model_name=_MODEL, revision=_REV, cache_dir=_CACHE)
    print("완료.\n")

    print("TRAIL 파일 목록 열거 중...")
    traces = _list_trail_traces(limit=_LIMIT)
    print(f"총 {len(traces)}개 선택됨.\n")

    results: list[dict] = []
    for label, split, hf_path in traces:
        print(f"[{label}] {hf_path} 처리 중...")
        try:
            r = _run_one(label, split, hf_path, embedder)
            results.append(r)
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}")
            results.append({
                "label": label, "split": split, "hf_path": hf_path,
                "n_spans": 0, "elapsed": 0.0,
                "requery_pairs": [],
            })

    md = _render_md(results)
    _OUT.write_text(md, encoding="utf-8")

    total = sum(len(r["requery_pairs"]) for r in results)
    print(f"\n→ {_OUT} 저장 완료")
    print(f"requery FIRE 총수: {total}건 / {len(results)}개 트레이스")


if __name__ == "__main__":
    main()
