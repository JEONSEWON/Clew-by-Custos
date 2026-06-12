"""field_test/run_field_test_router_fp.py

라우터(conditional-edge 함수) FP 진단.
목표 A: should_loop가 동일 값을 반복 반환할 때 거짓 FIRE 재현.
목표 B: 라우터 span vs 작업 노드 span 구별 신호 조사.
진단만 — 수정 없음.
src/clew 은 read-only import 만.
"""

import sys
from collections import Counter, defaultdict
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

# ── Frozen params ──────────────────────────────────────────────────────
PHI   = 0.514345
N     = 2
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV   = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE = Path(".cache/embeddings")

# ── 3개 모두 다른 researcher 응답 (라우터 FP와 분리하기 위해) ──────────
R1 = "첫 번째 조사 결과: 멀티에이전트 낭비의 기술적 원인 분석."
R2 = "두 번째 조사 결과: 비용 구조와 토큰 소비 패턴 검토."
R3 = "세 번째 조사 결과: 루프 종료 조건 및 핸드오프 최적화 방향."


class State(TypedDict):
    topic: str
    research: str
    loop_count: int


researcher_llm = FakeListLLM(responses=[R1, R2, R3])


def researcher_node(state: State) -> dict:
    out = researcher_llm.invoke(f"주제: {state['topic']}")
    return {"research": out, "loop_count": state.get("loop_count", 0) + 1}


def should_loop(state: State) -> str:
    # 3회 루프: should_loop 출력 순서 = ["researcher","researcher","__end__"]
    # loop_count < 3 → "researcher" (동일 문자열 2회 반복)
    return "researcher" if state["loop_count"] < 3 else END


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

    # [2] 실행 (3-loop)
    graph = build_graph()
    graph.invoke({"topic": "멀티에이전트 AI 토큰 낭비 원인", "research": "", "loop_count": 0})

    raw_spans = exporter.get_finished_spans()

    # ──────────────────────────────────────────────────────────────────
    # [CAPTURE-RAW] 모든 span의 전체 attribute dict
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print(f"[CAPTURE-RAW] 캡처된 span 수: {len(raw_spans)}")
    print(f"{'='*64}")
    for s in raw_spans:
        attrs = dict(s.attributes or {})
        parent_id = f"{s.parent.span_id:016x}" if s.parent else "None"
        print(f"\n  ── span: name={s.name!r}  parent={parent_id}")
        if not attrs:
            print("    (attributes 없음)")
        for k, v in sorted(attrs.items()):
            v_str = str(v)
            print(f"    {k} = {v_str[:100]!r}")

    # ──────────────────────────────────────────────────────────────────
    # [ADAPTER]
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print("[ADAPTER] otel_spans_to_trace()")
    print(f"{'='*64}")
    try:
        trace = otel_spans_to_trace(raw_spans)
    except ValueError as e:
        print(f"[ADAPTER GAP] {e}")
        return
    print(f"  OK — {len(trace.spans)}개 span")

    # ──────────────────────────────────────────────────────────────────
    # [COLLAPSE]
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print("[COLLAPSE] collapse_to_logical_nodes(trace)")
    print(f"{'='*64}")
    collapsed = collapse_to_logical_nodes(trace)
    print(f"  원본: {len(trace.spans)} → 변환 후: {len(collapsed.spans)}  (llm 제거: {collapsed.metadata['collapsed_llm_spans']})")
    print(f"\n  변환 후 span 목록 (시간순):")
    for sp in sorted(collapsed.spans, key=lambda s: s.start_time):
        print(f"    {sp.span_id[:12]}  kind={sp.span_kind:8s}  id={sp.agent_or_node_id!r:20s}  "
              f"out[:50]={sp.output_text[:50]!r}")

    # ──────────────────────────────────────────────────────────────────
    # [STRUCTURAL]
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print(f"[STRUCTURAL] find_candidates(N={N})")
    print(f"{'='*64}")
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE)
    candidates = find_candidates(collapsed, N)
    print(f"  총 후보 수: {len(candidates)}")
    for i, (origin, cand) in enumerate(candidates):
        cos_val = cosine(embedder.embed(origin.output_text), embedder.embed(cand.output_text))
        fire = "FIRE" if cos_val >= PHI else "no-fire"
        print(f"\n  [{i+1}] cosine={cos_val:.4f}  →  {fire}")
        print(f"    origin: id={origin.agent_or_node_id!r:20s}  out[:60]={origin.output_text[:60]!r}")
        print(f"    cand  : id={cand.agent_or_node_id!r:20s}  out[:60]={cand.output_text[:60]!r}")

    # ──────────────────────────────────────────────────────────────────
    # [CASCADE]
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print(f"[CASCADE] phi={PHI}, N={N}")
    print(f"{'='*64}")
    cr = cascade(collapsed, embedder, n=N, phi=PHI)
    print(f"  wasteful      : {cr.wasteful}")
    print(f"  waste_span_ids: {cr.waste_span_ids}")

    # ──────────────────────────────────────────────────────────────────
    # [ROUTER-FP] waste 판정된 span이 라우터인지 작업 노드인지 분류
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print("[ROUTER-FP] waste span 종류 분류")
    print(f"{'='*64}")
    span_map = {sp.span_id: sp for sp in collapsed.spans}
    router_fp_confirmed = False
    for sid in cr.waste_span_ids:
        sp = span_map.get(sid)
        if sp is None:
            print(f"  span_id={sid[:12]}  → (span 미발견)")
            continue
        label = "should_loop (라우터)" if sp.agent_or_node_id == "should_loop" else sp.agent_or_node_id
        if sp.agent_or_node_id == "should_loop":
            router_fp_confirmed = True
            verdict = "거짓 FIRE ✗ — 라우터가 낭비로 잘못 판정"
        else:
            verdict = "진짜 FIRE (작업 노드)"
        print(f"  span_id={sid[:12]}  agent_or_node_id={sp.agent_or_node_id!r}  → {verdict}")

    if router_fp_confirmed:
        print("\n  [결론 A] 버그 재현 성공 — should_loop(라우터)가 waste_span_ids에 포함됨.")
        print("  라우터가 동일 출력('researcher')을 반복 → cosine=1.0 > phi → 거짓 FIRE.")
    elif cr.wasteful:
        print("\n  [결론 A] wasteful=True이나 라우터 FP 없음 — 다른 span이 fire.")
    else:
        print("\n  [결론 A] wasteful=False — 버그 미재현 (예상 외).")

    # ──────────────────────────────────────────────────────────────────
    # [SIGNAL-PROBE] 구별 신호 3개를 모든 collapsed span에 적용
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print("[SIGNAL-PROBE] 라우터 vs 작업노드 구별 신호 조사")
    print(f"{'='*64}")

    # 신호 1: has_llm_or_tool_child — collapse 전 원본 trace에서 계산
    # (collapse 전 llm span이 어느 chain span의 자식인지)
    worker_parent_ids = {
        sp.parent_span_id
        for sp in trace.spans
        if sp.span_kind in ("llm", "tool") and sp.parent_span_id is not None
    }

    print(f"\n  ─ 신호 1: has_llm_or_tool_child (collapse 전 위상 기반) ─")
    print(f"  (llm/tool 자식을 가진 parent span_id 집합: {len(worker_parent_ids)}개)")

    print(f"\n  {'agent_or_node_id':22s} {'span_id[:12]':14s} {'kind':8s} "
          f"{'sig1_llm_tool_child':21s} {'sig2_token_count':17s} {'sig3_out_len':12s}")
    print(f"  {'-'*22} {'-'*14} {'-'*8} {'-'*21} {'-'*17} {'-'*12}")

    sig1_correct = True
    for sp in sorted(collapsed.spans, key=lambda s: s.start_time):
        sig1 = sp.span_id in worker_parent_ids  # True = 작업노드, False = 라우터 or root
        sig2 = sp.token_count  # None for most after collapse
        sig3 = len(sp.output_text)
        print(f"  {sp.agent_or_node_id:22s} {sp.span_id[:12]:14s} {sp.span_kind:8s} "
              f"{str(sig1):21s} {str(sig2):17s} {sig3:12d}")
        # 검증: should_loop은 sig1=False여야 하고, researcher는 True여야 함
        if sp.agent_or_node_id == "should_loop" and sig1:
            sig1_correct = False
        if sp.agent_or_node_id == "researcher" and not sig1:
            sig1_correct = False

    print(f"\n  ─ 신호 1 판정: {'올바르게 분리 ✓' if sig1_correct else '분리 실패 ✗'}")
    print(f"    researcher → has_llm_or_tool_child=True  (LLM 자식 보유)")
    print(f"    should_loop → has_llm_or_tool_child=False (자식 없음)")

    # ──────────────────────────────────────────────────────────────────
    # [RAW-ATTR-COMPARE] should_loop vs researcher 원시 속성 비교
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print("[RAW-ATTR-COMPARE] should_loop vs researcher 원시 OTel 속성 차이")
    print(f"{'='*64}")

    # 종류별 첫 번째 span만 비교
    sample: dict[str, object] = {}
    for s in raw_spans:
        name = s.name
        if name in ("should_loop", "researcher") and name not in sample:
            sample[name] = s

    for span_name in ("researcher", "should_loop"):
        s = sample.get(span_name)
        if s is None:
            print(f"  {span_name}: span 미발견")
            continue
        attrs = dict(s.attributes or {})
        parent_id = f"{s.parent.span_id:016x}" if s.parent else "None"
        print(f"\n  ── {span_name}  parent={parent_id}")
        all_keys = sorted(attrs.keys())
        print(f"  전체 attribute 키 ({len(all_keys)}개): {all_keys}")
        for k in all_keys:
            print(f"    {k} = {str(attrs[k])[:80]!r}")

    # ──────────────────────────────────────────────────────────────────
    # [VERDICT]
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print("[VERDICT]")
    print(f"{'='*64}")
    print("  목표 A — 라우터 거짓 FIRE 재현:")
    if router_fp_confirmed:
        print("    ✗ 버그 확인. should_loop(라우터)가 동일 출력 반복 → cosine=1.0 → false FIRE.")
        print("    원인: collapse가 llm span만 제거하고 라우터 chain span은 유지.")
        print("    이후 find_candidates(N=2)가 라우터를 반복 노드로 오인.")
    else:
        print("    (버그 미재현 — 로그 확인 필요)")

    print("\n  목표 B — 구별 신호 권고:")
    print("    권고: has_llm_or_tool_child (collapse 전 위상 기반)")
    if sig1_correct:
        print("    ✓ 신호 정확 — researcher(True) / should_loop(False) 올바르게 분리.")
    else:
        print("    ✗ 신호 부정확 — 로그 확인 필요.")
    print("    근거: 라우터는 순수 Python 분기 로직 → llm/tool 자식 span 없음.")
    print("          작업 노드는 반드시 llm/tool을 호출 → 자식 span 존재.")
    print("    한계: LLM-라우터(모델이 다음 노드 결정)는 구별 불가. 현재 스택엔 해당 없음.")
    print(f"\n  [원시 속성] LangGraph 전용 속성(langgraph.* 등) 존재 여부 →")
    print("    [CAPTURE-RAW] 섹션 참조. 없으면 위상 신호가 유일한 프레임워크-독립 수단.")
    print(f"{'='*64}\n")


if __name__ == "__main__":
    main()
