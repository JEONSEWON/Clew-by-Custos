"""tests/test_field_regressions.py — 인제스트 필드-하드닝 회귀 테스트 (R1~R5).

R1: 깨끗한 trace → FP=0
R2: repeat_node 패턴 → TP
R3: 라우터 적대 그래프 → 라우터 제거 + FP=0
R4: JSON 추출 후 cosine 하락 (마진 0.05)
R5: ReAct 고아 처리 단위 테스트 (llm→tool re-parent)

API 키 불요 — FakeListLLM + 합성 Span 픽스처 자급.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import pytest

pytest.importorskip("opentelemetry.sdk.trace")
pytest.importorskip("openinference.instrumentation.langchain")
pytest.importorskip("langgraph.graph")
pytest.importorskip("langchain_core.language_models.fake")

from langchain_core.language_models.fake import FakeListLLM
from langgraph.graph import END, StateGraph
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clew.detect.cascade import cascade
from clew.detect.semantic import Embedder, cosine
from clew.ingest.langgraph import ingest_otel_spans, otel_spans_to_trace
from clew.ingest.preprocess import (
    collapse_llm_spans,
    extract_output_text,
    mark_worker_span_ids,
    preprocess_trace,
)
from clew.model import Span, Trace

# ── Frozen params ──────────────────────────────────────────────────────────
PHI = 0.514345
N = 2
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE = Path(".cache/embeddings")

# ── Paraphrase pair (run_field_test_waste.py 동일 텍스트) ─────────────────
_R1_TEXT = (
    "멀티에이전트 AI에서 토큰 낭비 주요 원인: "
    "(1) 동일 정보 재조회 — 에이전트가 이미 확보한 정보를 같은 도구로 다시 요청한다. "
    "(2) 출력 재생성 — 다음 에이전트가 직전 에이전트의 결과를 동일 내용으로 다시 작성한다. "
    "(3) 루프 미종료 — 탈출 조건 없이 완료된 작업을 계속 반복한다."
)
_R2_TEXT = (
    "AI 멀티에이전트 시스템의 낭비 원인 요약: "
    "(1) 중복 조회 — 이미 가진 데이터를 반복해서 가져온다. "
    "(2) 결과 재작성 — 이전 에이전트 출력을 동일한 의미로 재생성한다. "
    "(3) 무한 반복 — 작업이 끝났음에도 루프가 계속 실행된다."
)


# ── 공통 헬퍼 ──────────────────────────────────────────────────────────────

class _State(TypedDict):
    topic: str
    research: str
    loop_count: int


def _capture_spans(responses: list[str], loop_limit: int) -> list:
    """FakeListLLM loopback 그래프 실행 → raw OTel spans.

    loop_limit: loop_count < loop_limit 이면 loopback, 아니면 END.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = LangChainInstrumentor()
    instrumentor.instrument(tracer_provider=provider, skip_dep_check=True)
    try:
        llm = FakeListLLM(responses=responses)

        def researcher_node(state: _State) -> dict:
            out = llm.invoke(f"주제: {state['topic']}")
            return {"research": out, "loop_count": state.get("loop_count", 0) + 1}

        def should_loop(state: _State) -> str:
            return "researcher" if state["loop_count"] < loop_limit else END

        g = StateGraph(_State)
        g.add_node("researcher", researcher_node)
        g.set_entry_point("researcher")
        g.add_conditional_edges(
            "researcher", should_loop, {"researcher": "researcher", END: END}
        )
        app = g.compile()
        app.invoke({"topic": "테스트 주제", "research": "", "loop_count": 0})
        provider.force_flush()
        return list(exporter.get_finished_spans())
    finally:
        instrumentor.uninstrument()


@pytest.fixture(scope="module")
def embedder():
    return Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE)


# ── R1: 깨끗한 trace — FP=0 ───────────────────────────────────────────────

def test_r1_clean_no_false_fire(embedder):
    """서로 다른 도메인 출력 2개 → 전처리 후 cascade wasteful=False."""
    spans = _capture_spans(
        ["기후 변화의 원인과 영향에 대한 분석 결과.", "경제 성장 지표와 GDP 변동 패턴 검토."],
        loop_limit=2,
    )
    raw_trace = otel_spans_to_trace(spans)
    trace = preprocess_trace(raw_trace)
    cr = cascade(trace, embedder, n=N, phi=PHI)
    assert not cr.wasteful


# ── R2: repeat_node — TP ──────────────────────────────────────────────────

def test_r2_repeat_node_true_positive(embedder):
    """패러프레이즈 쌍 → 전처리 후 cascade wasteful=True."""
    spans = _capture_spans([_R1_TEXT, _R2_TEXT], loop_limit=2)
    raw_trace = otel_spans_to_trace(spans)
    trace = preprocess_trace(raw_trace)
    cr = cascade(trace, embedder, n=N, phi=PHI)
    assert cr.wasteful
    # 코사인 앵커 검증
    assert cosine(embedder.embed(_R1_TEXT), embedder.embed(_R2_TEXT)) > PHI


# ── R3: 라우터 적대 — FP 소거 ─────────────────────────────────────────────

def test_r3_router_adversarial_no_false_fire(embedder):
    """should_loop가 'researcher'를 2회 반환하는 3-loop 그래프.
    전처리 후 should_loop span이 제거되고 cascade wasteful=False."""
    spans = _capture_spans(
        [
            "첫 번째: 멀티에이전트 루프 종료 조건 분석.",
            "두 번째: 핸드오프 비용 구조 검토.",
            "세 번째: 토큰 낭비 최적화 방향 제안.",
        ],
        loop_limit=3,
    )
    raw_trace = otel_spans_to_trace(spans)
    trace = preprocess_trace(raw_trace)
    node_ids = {sp.agent_or_node_id for sp in trace.spans}
    assert "should_loop" not in node_ids
    cr = cascade(trace, embedder, n=N, phi=PHI)
    assert not cr.wasteful


# ── R4: JSON 추출 후 cosine 하락 ──────────────────────────────────────────

def test_r4_json_extraction_reduces_cosine(embedder):
    """JSON 상태딕 전문 cosine > 추출 후 cosine, 마진 > 0.05.
    (실측: c_raw≈0.777, c_ext≈0.567, Δ≈0.21)"""
    raw_1 = '{"research": "첫 번째 조사 결과: 멀티에이전트 낭비의 기술적 원인 분석.", "loop_count": 1}'
    raw_2 = '{"research": "두 번째 조사 결과: 비용 구조와 토큰 소비 패턴 검토.", "loop_count": 2}'
    ext_1 = extract_output_text(raw_1)
    ext_2 = extract_output_text(raw_2)
    c_raw = cosine(embedder.embed(raw_1), embedder.embed(raw_2))
    c_ext = cosine(embedder.embed(ext_1), embedder.embed(ext_2))
    assert c_raw - c_ext > 0.05


# ── R5: ReAct 고아 처리 단위 테스트 ──────────────────────────────────────

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_LATER = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)


def _make_span(span_id: str, parent_id: str | None, kind: str) -> Span:
    return Span(
        trace_id="a" * 32,
        span_id=span_id,
        parent_span_id=parent_id,
        agent_or_node_id=span_id,
        span_kind=kind,  # type: ignore[arg-type]
        start_time=_NOW,
        end_time=_LATER,
        input_text="x",
        output_text="y",
    )


# ── R6: ingest_otel_spans 파이프라인 핀 고정 ──────────────────────────────

def test_r6_ingest_otel_spans_applies_preprocessing():
    """ingest_otel_spans()가 전처리를 실제로 적용함을 핀 고정.

    라우터 적대 스팬(3-loop) → 반환 Trace에서:
    - should_loop span 없음
    - llm span 0개
    - 모든 output_text에 JSON 스캐폴드 키 패턴('{"') 없음
    """
    spans = _capture_spans(
        [
            "첫 번째: 멀티에이전트 루프 종료 조건 분석.",
            "두 번째: 핸드오프 비용 구조 검토.",
            "세 번째: 토큰 낭비 최적화 방향 제안.",
        ],
        loop_limit=3,
    )
    trace = ingest_otel_spans(spans)

    node_ids = {sp.agent_or_node_id for sp in trace.spans}
    assert "should_loop" not in node_ids, "라우터 span이 제거되지 않음"

    llm_spans = [sp for sp in trace.spans if sp.span_kind == "llm"]
    assert len(llm_spans) == 0, f"llm span {len(llm_spans)}개 잔존"

    for sp in trace.spans:
        assert '{"' not in sp.output_text, (
            f"JSON 스캐폴드 키 패턴이 {sp.agent_or_node_id!r} output_text에 잔존: "
            f"{sp.output_text[:80]!r}"
        )


def test_r5_react_tool_reparented_after_llm_collapse():
    """합성 트리: root(chain) → worker(chain) → llm → tool
    collapse 후 tool이 worker로 re-parent되어 생존."""
    root   = _make_span("root",   None,     "chain")
    worker = _make_span("worker", "root",   "chain")
    llm    = _make_span("llm",    "worker", "llm")
    tool   = _make_span("tool",   "llm",    "tool")
    spans = [root, worker, llm, tool]

    worker_ids = mark_worker_span_ids(spans)
    assert "worker" in worker_ids  # worker는 llm 자손 보유

    kept, removed_count = collapse_llm_spans(spans, worker_ids)
    kept_ids = {s.span_id for s in kept}

    assert removed_count == 1
    assert "llm"  not in kept_ids           # llm 제거됨
    assert "tool" in kept_ids               # tool 생존
    tool_span = next(s for s in kept if s.span_id == "tool")
    assert tool_span.parent_span_id == "worker"  # worker로 re-parent
