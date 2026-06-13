"""field_test/run_field_test_waste.py

repeat_node 패턴이 심긴 트레이스에서 collapse 후에도 cascade FIRE 확인 (TP 보존).
깨끗한 케이스(run_field_test.py, FP=0)와 짝지어 실제 계측 위 정밀도+재현율 둘 다 검증.
src/clew 은 read-only import 만.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from clew.detect.cascade import cascade
from clew.detect.semantic import Embedder, cosine
from clew.detect.structural import find_candidates
from clew.ingest.langgraph import otel_spans_to_trace

sys.path.insert(0, str(Path(__file__).parent))
from collapse import collapse_to_logical_nodes

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from openinference.instrumentation.langchain import LangChainInstrumentor

from langgraph.graph import StateGraph, END
from langchain_core.language_models.fake import FakeListLLM
from typing import TypedDict

# ── Frozen params (stage2-eval-go 동결, 변경 금지) ─────────────────────
PHI   = 0.514345
N     = 2
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV   = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE = Path(".cache/embeddings")

# ── 패러프레이즈 쌍 — 동일 내용(재조회·재생성·루프미종료), 다른 표현 ──
# 바이트 동일 금지(v1 교훈): 완전히 다른 문장이지만 의미 동일 → cosine > phi 기대
RESEARCHER_RESPONSE_1 = (
    "멀티에이전트 AI에서 토큰 낭비 주요 원인: "
    "(1) 동일 정보 재조회 — 에이전트가 이미 확보한 정보를 같은 도구로 다시 요청한다. "
    "(2) 출력 재생성 — 다음 에이전트가 직전 에이전트의 결과를 동일 내용으로 다시 작성한다. "
    "(3) 루프 미종료 — 탈출 조건 없이 완료된 작업을 계속 반복한다."
)
RESEARCHER_RESPONSE_2 = (
    "AI 멀티에이전트 시스템의 낭비 원인 요약: "
    "(1) 중복 조회 — 이미 가진 데이터를 반복해서 가져온다. "
    "(2) 결과 재작성 — 이전 에이전트 출력을 동일한 의미로 재생성한다. "
    "(3) 무한 반복 — 작업이 끝났음에도 루프가 계속 실행된다."
)


# ── State & nodes ─────────────────────────────────────────────────────
class State(TypedDict):
    topic: str
    research: str
    loop_count: int


researcher_llm = FakeListLLM(responses=[RESEARCHER_RESPONSE_1, RESEARCHER_RESPONSE_2])


def researcher_node(state: State) -> dict:
    out = researcher_llm.invoke(f"주제: {state['topic']}")
    return {"research": out, "loop_count": state.get("loop_count", 0) + 1}


def should_loop(state: State) -> str:
    return "researcher" if state["loop_count"] < 2 else END


def build_graph():
    g = StateGraph(State)
    g.add_node("researcher", researcher_node)
    g.set_entry_point("researcher")
    g.add_conditional_edges("researcher", should_loop, {"researcher": "researcher", END: END})
    return g.compile()


def main():
    # [1] OTel 계측
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    LangChainInstrumentor().instrument(tracer_provider=provider)

    # [2] 실행 (researcher 2회: R1 → loopback → R2 → END)
    graph = build_graph()
    graph.invoke({
        "topic": "멀티에이전트 AI 토큰 낭비 원인",
        "research": "",
        "loop_count": 0,
    })

    # [3] CAPTURE — raw span 덤프
    spans = exporter.get_finished_spans()
    print(f"\n{'='*64}")
    print(f"[CAPTURE] 캡처된 span 수: {len(spans)}")
    print(f"{'='*64}")
    for s in spans:
        attrs = dict(s.attributes or {})
        kind_raw = attrs.get("openinference.span.kind", "(없음)")
        out_val  = str(attrs.get("output.value", "(없음)"))[:70]
        parent_id = f"{s.parent.span_id:016x}" if s.parent else "None"
        print(f"  name={s.name!r:40s} kind={kind_raw!r:10s} parent={parent_id}")
        if "(없음)" not in out_val:
            print(f"    output.value: {out_val!r}")

    # [4] ADAPTER
    print(f"\n{'='*64}")
    print("[ADAPTER] otel_spans_to_trace() 시도")
    print(f"{'='*64}")
    try:
        trace = otel_spans_to_trace(spans)
    except ValueError as e:
        print(f"[ADAPTER GAP] {e}")
        print("\n[SHIM] output 관련 attribute 덤프:")
        for s in spans:
            out_keys = {k: v for k, v in (s.attributes or {}).items()
                        if "output" in k.lower() or "message" in k.lower()}
            if out_keys:
                print(f"  span={s.name!r}")
                for k, v in out_keys.items():
                    print(f"    {k} = {str(v)[:80]!r}")
        return

    print(f"[ADAPTER OK] trace_id={trace.trace_id[:16]}…  총 {len(trace.spans)}개 span")

    # [5] COLLAPSE
    print(f"\n{'='*64}")
    print("[COLLAPSE] collapse_to_logical_nodes(trace)")
    print(f"{'='*64}")
    collapsed = collapse_to_logical_nodes(trace)
    removed_count = collapsed.metadata.get("collapsed_llm_spans", 0)
    print(f"  원본 span 수: {len(trace.spans)}  →  변환 후: {len(collapsed.spans)}")
    print(f"  제거된 llm span: {removed_count}")
    print(f"\n  변환 후 span 목록 (시간순):")
    for sp in sorted(collapsed.spans, key=lambda s: s.start_time):
        print(f"    {sp.span_id[:12]:12s} kind={sp.span_kind:8s} agent_or_node_id={sp.agent_or_node_id!r}")

    collapsed_id_counts = Counter(sp.agent_or_node_id for sp in collapsed.spans)
    researcher_count = collapsed_id_counts.get("researcher", 0)
    researcher_check = "✓" if researcher_count >= 2 else "✗ 기대 2회 미달"
    print(f"\n  researcher span 수: {researcher_count}  {researcher_check}")

    # [6] STRUCTURAL
    print(f"\n{'='*64}")
    print(f"[STRUCTURAL] find_candidates(collapsed, N={N})")
    print(f"{'='*64}")
    candidates = find_candidates(collapsed, N)
    expected_check = "✓" if len(candidates) == 1 else f"✗ 기대 1, 실제 {len(candidates)}"
    print(f"  후보 수: {len(candidates)}  {expected_check}")
    for origin, cand in candidates:
        print(f"  origin: id={origin.agent_or_node_id!r:20s} kind={origin.span_kind}")
        print(f"    out[:80]: {origin.output_text[:80]!r}")
        print(f"  cand  : id={cand.agent_or_node_id!r:20s} kind={cand.span_kind}")
        print(f"    out[:80]: {cand.output_text[:80]!r}")

    # [7] COSINE
    print(f"\n{'='*64}")
    print(f"[COSINE] embed(R1) · embed(R2)  (phi={PHI})")
    print(f"{'='*64}")
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE)
    cos_val = cosine(embedder.embed(RESEARCHER_RESPONSE_1), embedder.embed(RESEARCHER_RESPONSE_2))
    fire_check = "FIRE ✓" if cos_val >= PHI else f"NO-FIRE ✗ (< phi)"
    print(f"  cosine(R1, R2) = {cos_val:.6f}  →  {fire_check}")
    byte_check = "✓ 바이트 다름" if RESEARCHER_RESPONSE_1 != RESEARCHER_RESPONSE_2 else "✗ 동일"
    print(f"  R1 == R2? {RESEARCHER_RESPONSE_1 == RESEARCHER_RESPONSE_2}  {byte_check}")

    # [8] CASCADE
    print(f"\n{'='*64}")
    print(f"[CASCADE] phi={PHI}, N={N}  (collapsed trace)")
    print(f"{'='*64}")
    cr = cascade(collapsed, embedder, n=N, phi=PHI)
    wasteful_check = "✓" if cr.wasteful else "✗ 기대 True"
    print(f"  wasteful      : {cr.wasteful}  {wasteful_check}")
    print(f"  waste_span_ids: {cr.waste_span_ids}")
    print(f"  waste_tokens  : {cr.waste_tokens}  (FakeListLLM → 무의미)")
    print(f"  waste_cost    : {cr.waste_cost:.6f}  (FakeListLLM → 무의미)")

    # [9] WASTE DETAIL — origin/candidate 전문 나란히
    print(f"\n{'='*64}")
    print("[WASTE DETAIL] origin / candidate 전문 (바이트 동일 여부 육안 확인)")
    print(f"{'='*64}")
    if cr.waste_span_ids and candidates:
        span_map = {sp.span_id: sp for sp in collapsed.spans}
        for sid in cr.waste_span_ids:
            matching = [(o, c) for o, c in candidates if c.span_id == sid]
            if matching:
                o, c = matching[0]
                cv = cosine(embedder.embed(o.output_text), embedder.embed(c.output_text))
                print(f"  waste span_id: {sid[:12]}  cosine={cv:.6f}")
                print(f"  ── origin ──────────────────────────────────────────────────")
                print(f"  {o.output_text}")
                print(f"  ── candidate (waste) ────────────────────────────────────────")
                print(f"  {c.output_text}")
                print(f"  ── 바이트 동일: {o.output_text == c.output_text} ────────────────────────────────")
    else:
        print("  (waste span 없음 — cascade 미발화)")

    # [10] VERDICT
    print(f"\n{'='*64}")
    print("[VERDICT] 두 런 종합")
    print(f"{'='*64}")
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │ clean test (run_field_test.py)                          │")
    print("  │   → collapse 후 FP=0  →  FPR=0 ✓                      │")
    print("  │ waste test (this run)                                   │")
    tp_line = "  │   → collapse 후 TP=1  →  TPR=1 ✓                      │" if cr.wasteful \
        else "  │   → collapse 후 TP=0  →  TPR=0 ✗                      │"
    print(tp_line)
    print("  └─────────────────────────────────────────────────────────┘")
    if cr.wasteful:
        print("\n  실제 OTel 계측 위 정밀도+재현율 둘 다 성립.")
        print("  collapse는 FP를 소거하면서 TP를 보존한다.")
    else:
        print("\n  ✗ waste test 실패 — cascade 미발화. 원인 분석 필요.")
    print(f"{'='*64}\n")


if __name__ == "__main__":
    main()
