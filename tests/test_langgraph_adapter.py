"""tests/test_langgraph_adapter.py — LangGraph 어댑터 라운드트립.

LLM API 키 없이 결정론적으로 동작 (FakeListChatModel).
"""

from __future__ import annotations

from typing import TypedDict

import pytest

pytest.importorskip("opentelemetry.sdk.trace")
pytest.importorskip("openinference.instrumentation.langchain")
pytest.importorskip("langgraph.graph")
pytest.importorskip("langchain_core.language_models.fake_chat_models")

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, StateGraph
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clew.ingest.langgraph import otel_spans_to_trace
from clew.model import Trace


class _State(TypedDict):
    messages: list[str]


def _build_demo_graph():
    llm_a = FakeListChatModel(responses=["A response"])
    llm_b = FakeListChatModel(responses=["B response"])

    def node_a(state: _State) -> _State:
        out = llm_a.invoke(state["messages"][-1])
        return {"messages": state["messages"] + [out.content]}

    def node_b(state: _State) -> _State:
        out = llm_b.invoke(state["messages"][-1])
        return {"messages": state["messages"] + [out.content]}

    g = StateGraph(_State)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.set_entry_point("a")
    g.add_edge("a", "b")
    g.add_edge("b", END)
    return g.compile()


@pytest.fixture
def captured_spans():
    """작은 LangGraph 실행을 계측해 OTel 스팬 리스트 반환."""
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    instrumentor = LangChainInstrumentor()
    instrumentor.instrument(tracer_provider=provider, skip_dep_check=True)
    try:
        app = _build_demo_graph()
        app.invoke({"messages": ["hi"]})
        provider.force_flush()
        yield list(exporter.get_finished_spans())
    finally:
        instrumentor.uninstrument()


def test_adapter_returns_trace(captured_spans):
    trace = otel_spans_to_trace(captured_spans)
    assert isinstance(trace, Trace)


def test_adapter_span_count_preserved(captured_spans):
    trace = otel_spans_to_trace(captured_spans)
    assert len(trace.spans) == len(captured_spans)


def test_adapter_single_root(captured_spans):
    trace = otel_spans_to_trace(captured_spans)
    roots = [s for s in trace.spans if s.parent_span_id is None]
    assert len(roots) == 1


def test_adapter_parent_child_preserved(captured_spans):
    trace = otel_spans_to_trace(captured_spans)
    by_id = {s.span_id: s for s in trace.spans}
    for s in trace.spans:
        if s.parent_span_id is not None:
            assert s.parent_span_id in by_id


def test_adapter_llm_spans_have_output_text(captured_spans):
    trace = otel_spans_to_trace(captured_spans)
    llm_spans = [s for s in trace.spans if s.span_kind == "llm"]
    assert len(llm_spans) >= 2  # node_a / node_b 각 1개씩 LLM 호출
    for s in llm_spans:
        assert s.output_text.strip() != ""


def test_adapter_chain_spans_have_output_text(captured_spans):
    trace = otel_spans_to_trace(captured_spans)
    chain_spans = [s for s in trace.spans if s.span_kind == "chain"]
    assert len(chain_spans) >= 1
    for s in chain_spans:
        assert s.output_text.strip() != ""


def test_adapter_cost_rate_via_cost_table(captured_spans):
    # FakeListChatModel은 model_name이 아니라 llm.provider="fakelistchatmodel"을 발행.
    # _model_of 가 provider 폴백을 보므로 model="fakelistchatmodel".
    table = {"fakelistchatmodel": 1.5e-6}
    trace = otel_spans_to_trace(captured_spans, cost_table=table)
    llm_with_rate = [
        s for s in trace.spans if s.span_kind == "llm" and s.cost_rate is not None
    ]
    assert len(llm_with_rate) >= 1
    for s in llm_with_rate:
        assert s.cost_rate == pytest.approx(1.5e-6)


def test_adapter_roundtrip_through_json(captured_spans):
    trace = otel_spans_to_trace(captured_spans)
    raw = trace.model_dump_json()
    restored = Trace.model_validate_json(raw)
    assert restored == trace


def test_adapter_rejects_empty_spans():
    with pytest.raises(ValueError, match="no spans"):
        otel_spans_to_trace([])


def test_adapter_records_source_tag(captured_spans):
    trace = otel_spans_to_trace(captured_spans, source_tag="test_adapter")
    assert trace.metadata.get("source") == "test_adapter"
    assert trace.metadata.get("schema_version") == "1.0"
