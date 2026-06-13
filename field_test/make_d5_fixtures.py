"""field_test/make_d5_fixtures.py — D5 확인용 픽스처 생성.

(a) waste 트레이스: R2형 패러프레이즈 쌍 2회 loopback
(b) clean 트레이스: 서로 다른 도메인 2개

field_test/d5_waste.json, field_test/d5_clean.json 저장.
src/clew는 read-only import만.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from typing import TypedDict

from langchain_core.language_models.fake import FakeListLLM
from langgraph.graph import END, StateGraph
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clew.ingest.langgraph import ingest_otel_spans
from clew.io import save_trace

HERE = Path(__file__).parent

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


class _State(TypedDict):
    topic: str
    research: str
    loop_count: int


def _capture(responses: list[str], loop_limit: int) -> list:
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


if __name__ == "__main__":
    print("▶ waste 트레이스 생성 중...")
    waste_spans = _capture([_R1, _R2], loop_limit=2)
    waste_trace = ingest_otel_spans(waste_spans)
    save_trace(waste_trace, HERE / "d5_waste.json")
    print(f"  저장: {HERE / 'd5_waste.json'}  ({len(waste_trace.spans)} spans)")

    print("▶ clean 트레이스 생성 중...")
    clean_spans = _capture(
        ["기후 변화 원인과 영향에 대한 분석 결과.", "경제 성장 지표와 GDP 변동 패턴 검토."],
        loop_limit=2,
    )
    clean_trace = ingest_otel_spans(clean_spans)
    save_trace(clean_trace, HERE / "d5_clean.json")
    print(f"  저장: {HERE / 'd5_clean.json'}  ({len(clean_trace.spans)} spans)")
    print("완료.")
