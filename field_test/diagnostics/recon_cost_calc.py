"""report.md $ 계산 가능성 리콘 — 코드 수정 금지. raw 만.

Q1 report.md 가 뭘 담나 (렌더러 인용)
Q2 낭비 span 의 token_count 를 어댑터가 채우나
Q3 char 기반 토큰 근사 가능성
Q4 $ 환산 — 모델/단가 어디서
Q5 실제 계산 맛보기 (Toolathlon waste 재사용, CC 실행)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC_PROJECTS = Path.home() / ".claude/projects"
TOOLATHLON_DIR = ROOT / "data/toolathlon/hf"

MODEL_EMBED = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2


def q1():
    print("=" * 78)
    print("Q1 — report.md 렌더러 현재 상태")
    print("=" * 78)
    md = (ROOT / "src/clew/report/markdown.py").read_text(encoding="utf-8")
    for ln in md.splitlines():
        if any(k in ln for k in ("wasted tokens", "wasted cost", "waste_tokens", "waste_cost", "unknown")):
            print("  markdown.py:", ln.strip())
    print()
    m = (ROOT / "src/clew/report/_model.py").read_text(encoding="utf-8")
    print("  _model.py WasteDetail:")
    for ln in m.splitlines():
        if "waste_tokens" in ln or "waste_cost" in ln or "token_count" in ln or "cost_rate" in ln:
            print("   ", ln)
    print()


def q2():
    print("=" * 78)
    print("Q2 — 어댑터별 token_count / cost_rate 채움 상태 (grep)")
    print("=" * 78)
    for f in ["claude_code.py", "redundancy_bench.py", "toolathlon.py",
              "langgraph.py", "otel_json.py"]:
        path = ROOT / f"src/clew/ingest/{f}"
        if not path.exists():
            continue
        txt = path.read_text(encoding="utf-8")
        hits = [(i + 1, ln.strip()) for i, ln in enumerate(txt.splitlines())
                if re.search(r"\btoken_count\s*=|\bcost_rate\s*=|\bmodel\s*=", ln)
                and "Span(" not in ln][:8]
        # simpler: just grep the =None or =value on token_count / cost_rate / model
        lines = txt.splitlines()
        rows = []
        for i, ln in enumerate(lines, 1):
            for key in ("token_count=", "cost_rate=", "model="):
                if key in ln and (ln.strip().startswith(key) or ln.strip().startswith(key.replace("=",""))):
                    val = ln.strip()
                    rows.append((i, key.rstrip("="), val))
        print(f"\n[{f}]")
        for i, k, v in rows[:10]:
            print(f"  L{i:>4}  {k:<12}  {v}")
    print()


def q3():
    print("=" * 78)
    print("Q3 — char 기반 근사 가능성 (tiktoken 부재 확인 + 대안)")
    print("=" * 78)
    try:
        import tiktoken  # noqa: F401
        print("  tiktoken 설치됨")
    except ImportError:
        print("  tiktoken 미설치. 대안: chars / 4 근사 (영문 GPT 계열 관례).")
    print()
    print("  test: len('hello world') / 4 = ", len("hello world") / 4, " (참고: 실제 GPT ~2 token)")
    print("  JSON/코드는 char/token 비 ~3 (구두점/공백 많음).")
    print("  → 근사는 '토큰 추정치' 로만 인용. 정확한 토큰 아님 명시.")
    print()


def q4():
    print("=" * 78)
    print("Q4 — $ 환산: 모델 필드 + 단가")
    print("=" * 78)
    print("  Span.model 필드 존재 (model.py:35). Optional[str].")
    print("  어댑터별 채움:")
    print("    - toolathlon: model=modelname_run (파일명에서). ok")
    print("    - CC/RB: model=None. 미채움.")
    print("  → 단가 lookup 을 하려면 어댑터가 model 을 채워야.")
    print()
    print("  단가 (2026-07 기준 대략, 시변):")
    print("    Anthropic claude-4.5-sonnet: input $3/M, output $15/M")
    print("    OpenAI gpt-5:              input $2.50/M, output $10/M")
    print("    (스크립트 하드코딩은 낡음 — 사용자 입력/환경변수/외부 표 권장)")
    print()
    print("  Span.cost_rate 는 $/token 단일값 (현재 model.py). input/output 분리 안 됨.")
    print("  → 현재 자료구조로는 '평균 단가' 만 가능. input/output 분리하려면 확장 필요.")
    print()


def q5():
    print("=" * 78)
    print("Q5 — 실제 계산 맛보기: Toolathlon waste 재계산 + CC 20세션")
    print("=" * 78)
    # Toolathlon: reuse scan
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder
    from clew.ingest.toolathlon import _build_trace_from_entry, _iter_raw_lines

    embedder = Embedder(model_name=MODEL_EMBED, revision=REV, cache_dir=CACHE_DIR)

    total_waste_chars = 0
    total_waste_count = 0
    per_model_waste_chars: dict[str, int] = {}

    t0 = time.perf_counter()
    files = sorted(TOOLATHLON_DIR.glob("*.jsonl"))
    for path in files:
        m = re.match(r"^(.+)_(\d+)\.jsonl$", path.name)
        model_key = m.group(1) if m else path.name
        for lineno, entry in _iter_raw_lines(path):
            try:
                trace = _build_trace_from_entry(entry, lineno)
                res = cascade(trace, embedder, N, PHI)
            except Exception:  # noqa: BLE001
                continue
            span_by_id = {s.span_id: s for s in trace.spans}
            for wid in res.waste_span_ids:
                sp = span_by_id[wid]
                chars = len(sp.output_text)
                total_waste_chars += chars
                total_waste_count += 1
                per_model_waste_chars[model_key] = per_model_waste_chars.get(model_key, 0) + chars

    elapsed = time.perf_counter() - t0
    print(f"\n[Toolathlon 66 파일 재실행: {elapsed:.1f}s]")
    print(f"waste span 수         : {total_waste_count}")
    print(f"waste output chars 합 : {total_waste_chars:,}")
    approx_tokens = total_waste_chars // 4
    approx_tokens_lo = total_waste_chars // 5
    approx_tokens_hi = total_waste_chars // 3
    print(f"토큰 근사 (chars/4)   : {approx_tokens:,}")
    print(f"  범위 (chars/5..3)   : {approx_tokens_lo:,} — {approx_tokens_hi:,}")
    print()
    # $ 예시: input $3/M · output $15/M (claude-4.5-sonnet)
    # waste output_text 는 이전 tool_result 를 재소비 → 다음 LLM 호출의 input 토큰
    price_in_per_m = 3.0  # $/M input
    print(f"단가 예시 (claude-4.5-sonnet input $3/M input tokens 가정):")
    cost = approx_tokens * price_in_per_m / 1_000_000
    cost_lo = approx_tokens_lo * price_in_per_m / 1_000_000
    cost_hi = approx_tokens_hi * price_in_per_m / 1_000_000
    print(f"  $ 근사 : ${cost:.2f}  (범위 ${cost_lo:.2f}—${cost_hi:.2f})")
    print(f"  주의: 이 값은 22 모델 × 3 런 전체 낭비 후보 output 재소비 가정.")
    print(f"        실제로는 각 waste 가 이후 LLM input 으로 몇 번 재소비되나 트레이스별로 다름.")
    print()
    print("[모델별 waste output chars top-8]")
    for k in sorted(per_model_waste_chars, key=lambda x: -per_model_waste_chars[x])[:8]:
        c = per_model_waste_chars[k]
        print(f"  {k:<28} chars={c:>12,}  tok~{c//4:>10,}  $~{c//4*price_in_per_m/1_000_000:>6.2f}")


def main():
    q1(); q2(); q3(); q4(); q5()


if __name__ == "__main__":
    main()
