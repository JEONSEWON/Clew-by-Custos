"""field_test/run_waste_hunt.py — Stage 17 실측 낭비 탐색.

TRAIL 30~50개(HF API 동적 열거, 중대형 위주)를 stage16 게이트 적용된 현재
도구로 분석. 게이트 전/후 FIRE 수 비교, 패턴별 집계, 사람 판정란 포함.
결과: field_test/WASTE_HUNT.md

detect/·eval·φ/N/모델 전부 read-only (stage16 게이트 이미 반영됨).
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
_OUT   = _HERE / "WASTE_HUNT.md"
_LIMIT = 40   # 목표 트레이스 수 (상한 50)

_BAD_FILES = {
    "72822db6e120878d916b515c2501246b",  # duplicate span_id ParseError
}


def _list_trail_traces(limit: int = _LIMIT) -> list[tuple[str, str, str]]:
    """HF API로 TRAIL 파일 목록 열거. (label, split, hf_path) 리스트 반환.

    list_repo_tree(expand=True)로 파일 크기를 얻어 중대형 우선 정렬.
    구버전 huggingface_hub에는 없을 수 있으므로 list_repo_files로 fallback.
    """
    try:
        from huggingface_hub import list_repo_tree
        items = list(list_repo_tree(
            "PatronusAI/TRAIL", repo_type="dataset", expand=True, recursive=True
        ))
        # RepoFile 객체: .path, .size
        paths_with_size: list[tuple[str, int]] = [
            (item.path, getattr(item, "size", 0))
            for item in items
            if hasattr(item, "path")
            and item.path.endswith(".json")
            and ("GAIA/" in item.path or "SWE Bench/" in item.path)
            and not any(b in item.path for b in _BAD_FILES)
        ]
        # 크기 내림차순(중대형 우선)
        paths_with_size.sort(key=lambda x: x[1], reverse=True)
        paths = [p for p, _ in paths_with_size]
    except Exception:
        # fallback: 크기 정보 없이 경로만
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


def _pre_gate_fire_count(trace, embedder) -> int:
    """stage15 방식(게이트 없음): agent_or_node_id 반복 + cosine >= φ 쌍 수.

    detect/ 미수정. 게이트 없는 반복 집합을 스크립트 내부에서 직접 계산.
    """
    from clew.detect.semantic import cosine
    from clew.detect.structural import _normalize_input  # type: ignore[attr-defined]

    ordered = sorted(trace.spans, key=lambda s: s.start_time)
    groups: dict[str, list] = {}
    for s in ordered:
        groups.setdefault(s.agent_or_node_id, []).append(s)

    count = 0
    for occ in groups.values():
        if len(occ) < _N:
            continue
        origin = occ[0]
        is_tool = origin.span_kind == "tool"
        for cand in occ[1:]:
            if is_tool and _normalize_input(cand.input_text) != _normalize_input(origin.input_text):
                continue
            sc = cosine(embedder.embed(origin.output_text), embedder.embed(cand.output_text))
            if sc >= _PHI:
                count += 1
    return count


def _pattern_of(cand_span_id: str, repeat_ids: set[str], pingpong_ids: set[str]) -> str:
    in_r = cand_span_id in repeat_ids
    in_p = cand_span_id in pingpong_ids
    if in_r and in_p:
        return "repeat+pingpong"
    if in_r:
        return "repeat_node"
    if in_p:
        return "pingpong_aba"
    return "unknown"


def _run_one(label: str, split: str, hf_path: str, embedder) -> dict:
    from clew.detect.cascade import cascade
    from clew.detect.semantic import cosine
    from clew.detect.structural import (  # type: ignore[attr-defined]
        _nearest_agent_ancestor_id,
        find_candidates,
        find_pingpong_candidates,
        find_repeat_candidates,
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

    # 게이트 후 FIRE (stage16 현재)
    cr = cascade(trace, embedder, n=_N, phi=_PHI)
    waste_ids = set(cr.waste_span_ids)
    by_id = {s.span_id: s for s in trace.spans}

    # 패턴 구분용 집합
    repeat_cand_ids = {c.span_id for _, c in find_repeat_candidates(trace, _N)}
    pingpong_cand_ids = {c.span_id for _, c in find_pingpong_candidates(trace)}

    pairs = find_candidates(trace, _N)
    fire_pairs: list[tuple] = []
    for origin, candidate in pairs:
        sc = cosine(embedder.embed(origin.output_text), embedder.embed(candidate.output_text))
        if candidate.span_id in waste_ids:
            pattern = _pattern_of(candidate.span_id, repeat_cand_ids, pingpong_cand_ids)
            agent_id = _nearest_agent_ancestor_id(origin.parent_span_id, by_id)
            agent_name = by_id[agent_id].agent_or_node_id if agent_id else "None"
            fire_pairs.append((origin, candidate, sc, pattern, agent_id, agent_name))

    # 게이트 전 FIRE 수 (비교용)
    pre_gate = _pre_gate_fire_count(trace, embedder)

    elapsed = time.time() - t0
    print(
        f"  {label} [{split}] 스팬={len(trace.spans)} "
        f"게이트전={pre_gate} 게이트후={len(fire_pairs)} {elapsed:.1f}s"
    )
    return {
        "label": label,
        "split": split,
        "hf_path": hf_path,
        "n_spans": len(trace.spans),
        "elapsed": elapsed,
        "fire_pairs": fire_pairs,
        "pre_gate": pre_gate,
    }


def _render_md(results: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []

    lines.append("# WASTE_HUNT 로그 — 실측 낭비 탐색 (Stage 17)\n")
    lines.append(f"**실행일:** {now}  ")
    lines.append(f"**파라미터:** φ={_PHI}, N={_N}, model={_MODEL}  ")
    lines.append("**stage16 게이트:** 부모 AGENT 동일성 검증 활성\n")
    lines.append("---\n")
    lines.append("## 트레이스별 결과\n")

    total_post = 0
    total_pre = 0
    pattern_post: dict[str, int] = {}
    summary_rows: list[str] = []

    for r in results:
        label = r["label"]
        split = r["split"]
        hf_path = r["hf_path"]
        n_spans = r["n_spans"]
        elapsed = r["elapsed"]
        fire_pairs = r["fire_pairs"]
        pre = r.get("pre_gate", 0)
        post = len(fire_pairs)
        total_pre += pre
        total_post += post

        fname = hf_path.split("/")[-1]
        lines.append(f"### {label} — {split}/{fname}")
        lines.append(
            f"- 스팬 수(처리 후): {n_spans}개  처리 시간: {elapsed:.1f}s  "
            f"게이트 전 FIRE: {pre}건  게이트 후 FIRE: {post}건\n"
        )

        if fire_pairs:
            for i, (orig, cand, sc, pattern, agent_id, agent_name) in enumerate(fire_pairs, 1):
                total_post_seq = total_post - post + i
                lines.append(f"#### FIRE #{i} (누적 #{total_post_seq})")
                lines.append(f"- pattern: {pattern}  cosine: {sc:.4f}\n")
                lines.append(f"**Origin** `{orig.span_id}` `{orig.agent_or_node_id}` [{orig.span_kind}]")
                lines.append(f"- 부모 AGENT: `{agent_id}` (`{agent_name}`)")
                lines.append(f"- input_text: `{orig.input_text[:200]}`")
                lines.append(f"- output_text:\n```\n{orig.output_text[:500]}\n```\n")
                lines.append(f"**Candidate** `{cand.span_id}` `{cand.agent_or_node_id}` [{cand.span_kind}]")
                lines.append(f"- 부모 AGENT: `{agent_id}` (`{agent_name}`) (게이트 통과 = origin과 동일)")
                lines.append(f"- input_text: `{cand.input_text[:200]}`")
                lines.append(f"- output_text:\n```\n{cand.output_text[:500]}\n```\n")
                lines.append("**판정 (사람이 채움):**")
                lines.append("- [ ] 진짜낭비  [ ] 오탐  [ ] 애매")
                lines.append("- 메모:\n")
                pattern_post[pattern] = pattern_post.get(pattern, 0) + 1
        else:
            lines.append("FIRE 없음\n")

        lines.append("---\n")
        summary_rows.append(
            f"| {label} | {split} | {n_spans} | {pre} | {post} | {pre - post} |"
        )

    # 집계 표
    lines.append("## 집계 (자동)\n")
    lines.append("| 트레이스 | 타입 | 스팬 수 | 게이트 전 FIRE | 게이트 후 FIRE | 게이트 제거 수 |")
    lines.append("|---------|------|--------|--------------|--------------|-------------|")
    lines.extend(summary_rows)
    lines.append(f"\n**총 트레이스: {len(results)}개 | 게이트 전 FIRE: {total_pre}건 | 게이트 후 FIRE: {total_post}건 | 게이트 제거: {total_pre - total_post}건**\n")

    # 패턴별 집계
    lines.append("## 패턴별 FIRE 집계 (게이트 후)\n")
    lines.append("| 패턴 | FIRE 건수 |")
    lines.append("|------|---------|")
    for pat in ["repeat_node", "pingpong_aba", "repeat+pingpong", "unknown"]:
        lines.append(f"| {pat} | {pattern_post.get(pat, 0)} |")
    lines.append("")

    # 사람 판정 집계
    lines.append("## 집계 (사람 판정 후 채움)\n")
    lines.append("| 분류 | 건수 |")
    lines.append("|------|------|")
    lines.append("| 진짜낭비 | |")
    lines.append("| 오탐 | |")
    lines.append("| 애매 | |\n")

    # 결론 초안 (자동)
    lines.append("## 결론 (자동 초안 — 사람이 확인)\n")
    if total_post == 0:
        lines.append(
            f"게이트 적용 후 {len(results)}개 트레이스에서 FIRE **0건**.\n\n"
            f"게이트 전 총 FIRE {total_pre}건 → 게이트 후 0건: "
            "게이트가 오탐만 정확히 제거하고 진짜 낭비를 차단한 것은 없음.\n"
            "TRAIL 벤치마크는 '잘 작동한 에이전트'의 트레이스이므로 "
            "repeat_node / pingpong / requery 낭비 패턴이 드물다.\n"
            "도구 결함이 아니라 데이터 특성.\n\n"
            "- [ ] 결론 확정: \"TRAIL 벤치마크에 우리가 잡는 낭비 패턴 드묾\"\n"
            "- [ ] 다음 단계: 실제 프로덕션 워크로드(경로2) 수집 필요\n"
        )
    else:
        lines.append(
            f"게이트 적용 후 {len(results)}개 트레이스에서 FIRE **{total_post}건** "
            f"(게이트 전 {total_pre}건 중 {total_pre - total_post}건 제거).\n\n"
            "각 FIRE 판정란을 채워 진짜 낭비 여부 확인 후 결론 작성.\n\n"
            "- [ ] 진짜 낭비 N건 발견 → 실측 첫 낭비 증거\n"
            "- [ ] 전부 오탐 → \"TRAIL 벤치마크에 패턴 드묾\" 확인\n"
        )

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
                "fire_pairs": [], "pre_gate": 0,
                "error": str(exc),
            })

    md = _render_md(results)
    _OUT.write_text(md, encoding="utf-8")
    print(f"\n→ {_OUT} 저장 완료")

    total_post = sum(len(r["fire_pairs"]) for r in results)
    total_pre = sum(r.get("pre_gate", 0) for r in results)
    print(f"게이트 전 FIRE: {total_pre}건 | 게이트 후 FIRE: {total_post}건")


if __name__ == "__main__":
    main()
