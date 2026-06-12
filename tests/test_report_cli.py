"""tests/test_report_cli.py — 3단계 리포트 & CLI 회귀 테스트 (D1~D3).

D1: 낭비 픽스처 → 리포트 내용 단언 (노드명, cosine, 스니펫 ≤80, 1:1 dedupe)
D2: 깨끗 픽스처 → 미탐지 문구
D3: save_trace → load_trace 후 cascade 결과 동일

API 키 불요 — FakeListLLM 픽스처 자급.
"""

from __future__ import annotations

import json
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
from clew.detect.structural import find_candidates
from clew.ingest.langgraph import otel_spans_to_trace
from clew.ingest.preprocess import preprocess_trace
from clew.io import load_trace, save_trace
from clew.report._model import WasteDetail
from clew.report.json_report import render_json
from clew.report.markdown import render_markdown

# ── Frozen params ──────────────────────────────────────────────────────────
PHI = 0.514345
N = 2
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE = Path(".cache/embeddings")

# ── Paraphrase pair (test_field_regressions.py 동일 텍스트) ───────────────
_R1 = (
    "멀티에이전트 AI에서 토큰 낭비 주요 원인: "
    "(1) 동일 정보 재조회 — 에이전트가 이미 확보한 정보를 같은 도구로 다시 요청한다. "
    "(2) 출력 재생성 — 다음 에이전트가 직전 에이전트의 결과를 동일 내용으로 다시 작성한다. "
    "(3) 루프 미종료 — 탈출 조건 없이 완료된 작업을 계속 반복한다."
)
_R2 = (
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


def _build_details(trace, cr, emb) -> list[WasteDetail]:
    """candidate 기준 최고 cosine 쌍 1개 유지 (dedupe)."""
    waste_id_set = set(cr.waste_span_ids)
    pairs = find_candidates(trace, N)
    best: dict[str, tuple] = {}
    for origin, candidate in pairs:
        if candidate.span_id not in waste_id_set:
            continue
        score = cosine(
            emb.embed(origin.output_text),
            emb.embed(candidate.output_text),
        )
        if candidate.span_id not in best or score > best[candidate.span_id][2]:
            best[candidate.span_id] = (origin, candidate, score)
    return [WasteDetail(o, c, sc) for o, c, sc in best.values()]


@pytest.fixture(scope="module")
def embedder():
    return Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE)


# ── D1: 낭비 픽스처 → 리포트 내용 단언 ───────────────────────────────────

def test_d1_waste_report_contains_key_fields(embedder, tmp_path):
    spans = _capture_spans([_R1, _R2], loop_limit=2)
    trace = preprocess_trace(otel_spans_to_trace(spans))
    cr = cascade(trace, embedder, n=N, phi=PHI)
    assert cr.wasteful

    details = _build_details(trace, cr, embedder)

    # candidate 기준 1:1 dedupe
    assert len(details) == len(cr.waste_span_ids)

    # 마크다운
    md = render_markdown(trace, cr, details)
    assert "researcher" in md        # 낭비 노드 이름
    assert "0." in md                # cosine 값 (0.xxxx 형태)

    # JSON
    j = json.loads(render_json(trace, cr, details))
    assert j["wasteful"] is True
    assert len(j["waste_details"]) > 0
    # 스니펫 ≤80자 (기본 절단 검증)
    for wd in j["waste_details"]:
        if "snippet" in wd:
            assert len(wd["snippet"]) <= 80


# ── D2: 깨끗 픽스처 → 미탐지 문구 ────────────────────────────────────────

def test_d2_clean_report_no_waste(embedder):
    spans = _capture_spans(
        ["기후 변화 원인과 영향에 대한 분석 결과.", "경제 성장 지표와 GDP 변동 패턴 검토."],
        loop_limit=2,
    )
    trace = preprocess_trace(otel_spans_to_trace(spans))
    cr = cascade(trace, embedder, n=N, phi=PHI)
    assert not cr.wasteful

    md = render_markdown(trace, cr, [])
    assert "no waste detected" in md.lower()


# ── D3: 직렬화 왕복 후 cascade 결과 동일 ─────────────────────────────────

def test_d3_serialization_roundtrip(embedder, tmp_path):
    spans = _capture_spans([_R1, _R2], loop_limit=2)
    trace = preprocess_trace(otel_spans_to_trace(spans))

    save_trace(trace, tmp_path / "t.json")
    loaded = load_trace(tmp_path / "t.json")

    cr1 = cascade(trace,  embedder, n=N, phi=PHI)
    cr2 = cascade(loaded, embedder, n=N, phi=PHI)

    assert cr1.wasteful        == cr2.wasteful
    assert cr1.waste_span_ids  == cr2.waste_span_ids
    assert cr1.waste_tokens    == cr2.waste_tokens
