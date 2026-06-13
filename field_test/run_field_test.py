"""field_test/run_field_test.py

플러밍 + node 식별 보존 검증 (FakeListChatModel, API 비용 0).
cascade frozen params: phi=0.514345, N=2.
목적: 어댑터 호환성 + 탐지기 거동 확인.
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

# ── Fake responses (노드별로 의도적으로 다른 내용) ────────────────────
RESEARCHER_RESPONSE = (
    "멀티에이전트 AI에서 토큰 낭비 주요 원인 3가지: "
    "(1) 동일 정보 재조회 — 에이전트가 이미 가진 컨텍스트를 재확인하기 위해 "
    "같은 도구 호출을 반복한다. "
    "(2) 핸드오프 재생성 — 에이전트 B가 에이전트 A의 출력을 받고도 "
    "같은 내용을 자신의 말로 다시 쓴다. "
    "(3) 루프 미종료 — 종료 조건이 명확하지 않아 에이전트가 "
    "완료된 작업을 반복 수행한다."
)
SUMMARIZER_RESPONSE = (
    "3줄 요약: "
    "① 재조회 낭비: 캐시 없는 반복 도구 호출. "
    "② 핸드오프 중복: B가 A 결과를 그대로 재작성. "
    "③ 루프 미종료: 종료 신호 부재로 반복 실행."
)
CRITIC_RESPONSE = (
    "요약 평가: 원인을 명확히 압축했으나 각 원인의 비용 규모가 빠졌다. "
    "개선 방향: 원인별 평균 낭비 토큰 수 또는 비율을 추가하면 "
    "우선순위 결정에 도움이 된다."
)


# ── State & nodes ─────────────────────────────────────────────────────
class State(TypedDict):
    topic: str
    research: str
    summary: str
    critique: str


researcher_llm = FakeListLLM(responses=[RESEARCHER_RESPONSE])
summarizer_llm = FakeListLLM(responses=[SUMMARIZER_RESPONSE])
critic_llm     = FakeListLLM(responses=[CRITIC_RESPONSE])


def researcher_node(state: State) -> dict:
    out = researcher_llm.invoke(f"주제: {state['topic']}")
    return {"research": out}


def summarizer_node(state: State) -> dict:
    out = summarizer_llm.invoke(f"다음을 3줄 요약: {state['research']}")
    return {"summary": out}


def critic_node(state: State) -> dict:
    out = critic_llm.invoke(f"요약 평가: {state['summary']}")
    return {"critique": out}


def build_graph():
    g = StateGraph(State)
    g.add_node("researcher", researcher_node)
    g.add_node("summarizer", summarizer_node)
    g.add_node("critic",     critic_node)
    g.set_entry_point("researcher")
    g.add_edge("researcher", "summarizer")
    g.add_edge("summarizer", "critic")
    g.add_edge("critic", END)
    return g.compile()


def main():
    # [1] OTel 계측
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    LangChainInstrumentor().instrument(tracer_provider=provider)

    # [2] 실행
    graph = build_graph()
    graph.invoke({
        "topic": "멀티에이전트 AI 토큰 낭비 원인",
        "research": "", "summary": "", "critique": "",
    })

    # [3] Span 캡처 raw 덤프
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

    # [4] 어댑터 시도
    print(f"\n{'='*64}")
    print("[ADAPTER] otel_spans_to_trace() 시도")
    print(f"{'='*64}")
    try:
        trace = otel_spans_to_trace(spans)
    except ValueError as e:
        print(f"[ADAPTER GAP] {e}")
        print("\n[SHIM] 전체 span attribute 덤프 (output.value 탐색용):")
        for s in spans:
            out_keys = {k: v for k, v in (s.attributes or {}).items()
                        if "output" in k.lower() or "message" in k.lower()}
            if out_keys:
                print(f"  span={s.name!r}")
                for k, v in out_keys.items():
                    print(f"    {k} = {str(v)[:80]!r}")
        return

    # [4b] collapse_to_logical_nodes
    print(f"\n{'='*64}")
    print("[COLLAPSE] collapse_to_logical_nodes(trace)")
    print(f"{'='*64}")
    collapsed = collapse_to_logical_nodes(trace)
    removed_count = collapsed.metadata.get("collapsed_llm_spans", 0)
    tool_kept = [sp for sp in collapsed.spans if sp.span_kind == "tool"]
    print(f"  원본 span 수: {len(trace.spans)}  →  변환 후: {len(collapsed.spans)}")
    print(f"  제거된 llm span: {removed_count}  |  tool span 유지: {len(tool_kept)} (미제거 확인)")
    print(f"\n  변환 후 span 목록:")
    for sp in sorted(collapsed.spans, key=lambda s: s.start_time):
        print(f"    {sp.span_id[:12]:12s} kind={sp.span_kind:8s} agent_or_node_id={sp.agent_or_node_id!r}")

    # [5] 캐노니컬 트레이스 요약
    print(f"\n[ADAPTER OK] trace_id={trace.trace_id[:16]}…  총 {len(trace.spans)}개 span\n")
    sorted_spans = sorted(trace.spans, key=lambda s: s.start_time)
    print(f"  {'span_id':12s} {'agent_or_node_id':32s} {'span_kind':8s} output[:60]")
    print(f"  {'-'*12} {'-'*32} {'-'*8} {'-'*60}")
    for sp in sorted_spans:
        out_p = sp.output_text[:60].replace('\n', ' ')
        print(f"  {sp.span_id[:12]:12s} {sp.agent_or_node_id:32s} {sp.span_kind:8s} {out_p!r}")

    # [6] node_id 중복 분석 (핵심 점검)
    print(f"\n{'='*64}")
    print("[NODE ID ANALYSIS]")
    id_counts = Counter(sp.agent_or_node_id for sp in trace.spans)
    llm_spans = [sp for sp in trace.spans if sp.span_kind == "llm"]
    print(f"  llm span 수: {len(llm_spans)}")
    for sp in llm_spans:
        print(f"    {sp.span_id[:12]:12s} agent_or_node_id={sp.agent_or_node_id!r}")

    repeated_ids = [nid for nid, cnt in id_counts.items() if cnt >= N]
    if repeated_ids:
        print(f"\n  ⚠ agent_or_node_id 중복(≥N={N}): {repeated_ids}")
        print("  → 이는 탐지기 오류가 아닌 '계측이 node 정체성 보존 안 함' = 어댑터/계측 갭.")
        print("  교정 방향 검토: LLM-call span의 agent_or_node_id 를")
        print("    span.name(모델 클래스명) 대신 부모 chain span의 name(LangGraph node명)으로 교체.")
    else:
        print(f"  ✓ 모든 agent_or_node_id 고유 (N={N} 미만 반복)")

    # [7] 구조 후보
    candidates = find_candidates(trace, N)
    print(f"\n{'='*64}")
    print(f"[STRUCTURAL] find_candidates(N={N}) → {len(candidates)}개 후보")
    for origin, cand in candidates:
        is_artifact = (origin.agent_or_node_id == cand.agent_or_node_id
                       and id_counts[origin.agent_or_node_id] >= N)
        tag = "[ID 뭉침 아티팩트 — 어댑터/계측 갭]" if is_artifact else "[구조 반복]"
        print(f"  {tag}")
        print(f"    origin: id={origin.agent_or_node_id!r:20s} out={origin.output_text[:60]!r}")
        print(f"    cand  : id={cand.agent_or_node_id!r:20s} out={cand.output_text[:60]!r}")

    # [8] Cascade
    print(f"\n{'='*64}")
    print(f"[CASCADE] phi={PHI}, N={N}")
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE)
    cr = cascade(trace, embedder, n=N, phi=PHI)
    print(f"  wasteful      : {cr.wasteful}")
    print(f"  waste_span_ids: {cr.waste_span_ids}")
    print(f"  waste_tokens  : {cr.waste_tokens}  (FakeListChatModel → 무의미)")
    print(f"  waste_cost    : {cr.waste_cost:.6f}  (FakeListChatModel → 무의미)")

    if cr.waste_span_ids:
        span_map = {sp.span_id: sp for sp in trace.spans}
        print(f"\n[WASTE SPANS 원문 + cosine]")
        for sid in cr.waste_span_ids:
            matching = [(o, c) for o, c in candidates if c.span_id == sid]
            if matching:
                o, c = matching[0]
                cos_val = cosine(embedder.embed(o.output_text), embedder.embed(c.output_text))
                is_artifact = (o.agent_or_node_id == c.agent_or_node_id
                               and id_counts[o.agent_or_node_id] >= N)
                verdict = "ID 뭉침 아티팩트 (계측 갭)" if is_artifact else "진짜 중복 fire"
                print(f"  span={sid[:12]}  cosine={cos_val:.4f}  → {verdict}")
                print(f"    origin: {o.output_text[:80]!r}")
                print(f"    cand  : {c.output_text[:80]!r}")

    # [6b] 변환 후 cascade (가짜 fire 소거 확인)
    print(f"\n{'='*64}")
    print(f"[CASCADE-AFTER-COLLAPSE] phi={PHI}, N={N}")
    from collections import Counter as _Counter
    collapsed_id_counts = _Counter(sp.agent_or_node_id for sp in collapsed.spans)
    collapsed_candidates = find_candidates(collapsed, N)
    print(f"  변환 후 agent_or_node_id 분포: {dict(collapsed_id_counts)}")
    print(f"  find_candidates(N={N}) → {len(collapsed_candidates)}개 (0 기대)")
    cr2 = cascade(collapsed, embedder, n=N, phi=PHI)
    print(f"  wasteful: {cr2.wasteful}  (False 기대)")
    print(f"  waste_span_ids: {cr2.waste_span_ids}")
    before_verdict = "가짜 fire" if cr.wasteful else "정상"
    after_verdict  = "가짜 fire 소거 ✓" if (cr.wasteful and not cr2.wasteful) else (
        "원래도 정상" if (not cr.wasteful and not cr2.wasteful) else "예상 밖 결과")
    print(f"\n  BEFORE collapse → wasteful={cr.wasteful}  ({before_verdict})")
    print(f"  AFTER  collapse → wasteful={cr2.wasteful}  ({after_verdict})")

    # [9] 프레이밍
    print(f"\n{'='*64}")
    print("[FRAMING] 이 런 = 플러밍 + node 식별 보존 검증.")
    print("  후보 0개여도 '정밀도 검증됨' 아님 — 실제 출력 다양성은 실제 API 런에서.")
    print("  waste_tokens/cost 는 FakeListChatModel 이라 무의미.")
    print(f"{'='*64}\n")


if __name__ == "__main__":
    main()
